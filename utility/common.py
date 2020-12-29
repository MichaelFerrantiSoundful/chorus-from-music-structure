import numpy as np
import matplotlib.pyplot as plt
from typing import List

from configs.configs import DEBUG, logger
from configs.modelConfigs import (
    CC_PRECISION,
    CC_RECALL,
    EPSILON,
    MINIMUM_CHORUS_DUR,
    CLF_TARGET_LABEL,
    CLF_NON_TARGET_LABEL,
)
from collections import defaultdict


def cliqueTails(clique):
    nxt = np.array(clique) + 1
    nxt = sorted(set(nxt) - set(clique))
    return nxt


def cliqueHeads(clique):
    prv = np.array(clique) - 1
    prv = sorted(set(prv) - set(clique))
    prv = [x + 1 for x in prv]
    return prv


def cliqueGroups(clique):
    heads = cliqueHeads(clique)
    groups = [[clique[0]]]
    for idx in clique[1:]:
        if idx in heads:
            groups.append([idx])
        else:
            groups[-1].append(idx)
    return groups


def filteredCliqueEnds(clique, min_size=1, gap=5):
    groups = cliqueGroups(clique)
    heads = [group[0] for group in groups if len(group) >= min_size]
    tails = [group[-1] + 1 for group in groups if len(group) >= min_size]
    if len(heads) > 0:
        hs, ts = [heads[0]], []
        for nxtHead, tail in zip(heads[1:], tails[:-1]):
            if nxtHead - tail >= gap:
                hs.append(nxtHead)
                ts.append(tail)
        ts.append(tails[-1])
        return np.array(hs), np.array(ts)
    else:
        return np.array([]), np.array([])


def intervalIntersection(intv0, intv1):
    x = min(intv0[1], intv1[1]) - max(intv0[0], intv1[0])
    x = 0 if x < 0 else x
    return x


def filterIntvs(mirexFmt, fun=CLF_TARGET_LABEL):
    intvs, labels = mirexFmt
    labels = extractFunctions(labels, [fun])
    intvs = intvs[labels == fun]
    return intvs


def mergeIntervals(mirexFmt):
    intervals, labels = mirexFmt
    new_intervals = [intervals[0]]
    new_labels = [labels[0]]
    for interval, label in zip(intervals[1:], labels[1:]):
        if label == new_labels[-1]:
            new_intervals[-1][1] = interval[1]
        else:
            new_intervals.append(interval)
            new_labels.append(label)
    new_intervals = np.array(new_intervals)
    new_labels = np.array(new_labels, dtype="U16")
    return (new_intervals, new_labels)


def extractFunctions(
    labels: np.ndarray, funs: List[str] = [CLF_TARGET_LABEL]
) -> np.ndarray:
    newLabels = []
    for label in labels:
        # if label startswith any functional string
        preds = list(map(lambda fun: label.lower().startswith(fun), funs))
        if any(preds):
            newLabels.append(funs[preds.index(True)])
        else:
            newLabels.append("others")
    return np.array(newLabels, dtype="U16")


def matchLabel(est_intvs, gt):
    ref_intvs = filterIntvs(gt)
    gt_est_labels = []
    for onset, offset in est_intvs:
        intersec = sum(
            [intervalIntersection(intv, (onset, offset)) for intv in ref_intvs]
        )
        est_dur = offset - onset
        predicate = all(
            [
                intersec >= est_dur / 2,
            ]
        )
        label = CLF_TARGET_LABEL if predicate else CLF_NON_TARGET_LABEL
        gt_est_labels.append(label)
    return np.array(gt_est_labels)


def matchCliqueLabel(intervals, cliques, gt):
    labels = np.full(intervals.shape[0], CLF_NON_TARGET_LABEL, dtype="U16")
    clabels = getCliqueLabels(gt, cliques, intervals)
    for c, l in zip(cliques, clabels):
        for i in c:
            labels[i] = l
    mirexFmt = (intervals, labels)
    return mirexFmt


def getCliqueLabels(gt, cliques, intervals):
    gt = mergeIntervals(gt)
    ref_intvs = filterIntvs(gt)
    cliqueLabels = []
    for clique in cliques:
        cintvs = [
            (intervals[group[0]][0], intervals[group[-1]][1])
            for group in cliqueGroups(clique)
        ]
        intersec = np.sum(
            [
                intervalIntersection(intv, cintv)
                for cintv in cintvs
                for intv in ref_intvs
            ]
        )
        cdur = sum([(offset - onset) for onset, offset in cintvs])
        hit_ref_duration = np.sum(
            [
                intv[1] - intv[0]
                for intv in ref_intvs
                if np.sum([intervalIntersection(intv, cintv) for cintv in cintvs]) > 0
            ]
        )
        p = intersec / cdur if cdur > 0 else 0
        r = intersec / hit_ref_duration if hit_ref_duration > 0 else 0
        predicate = all(
            [
                p >= CC_PRECISION,
                r >= CC_RECALL,
                cdur >= MINIMUM_CHORUS_DUR,
            ]
        )
        # ml = matchLabel(cintvs, gt)
        # predicate = sum(ml == CLF_TARGET_LABEL) >= len(ml) * 0.5
        label = CLF_TARGET_LABEL if predicate else CLF_NON_TARGET_LABEL
        cliqueLabels.append(label)
    return cliqueLabels


def cliquesFromArr(arr):
    # key:clique label
    # value:frame number list
    cliquesDic = defaultdict(list)
    for i, label in enumerate(arr):
        cliquesDic[label].append(i)
    newCliques = list(cliquesDic.values())
    newCliques = sorted(newCliques, key=lambda c: c[0])
    return newCliques


def getLabeledSSM(cliques, size):
    boundaries = np.arange(size + 1, dtype=int)
    labeledSSM = np.zeros((size, size), dtype=int)
    for flag, clique in enumerate(cliques):
        groups = cliqueGroups(clique)
        for xgrp in groups:
            for ygrp in groups:
                xbegin, xend = boundaries[xgrp[0]], boundaries[xgrp[-1] + 1]
                ybegin, yend = boundaries[ygrp[0]], boundaries[ygrp[-1] + 1]
                labeledSSM[xbegin:xend, ybegin:yend] = flag + 1
    return labeledSSM


def logSSM(ssm, inplace=True):
    if not inplace:
        ssm = ssm.copy()
    ssm[ssm < 0] = 0
    ssm += EPSILON
    ssm = np.log(ssm)
    return ssm


def expSSM(ssm, inplace=True):
    if not inplace:
        ssm = ssm.copy()
    ssm = np.exp(ssm)
    ssm -= EPSILON
    ssm[ssm < 0] = 0
    return ssm


def singleChorusSection(begin, end, dur):
    intervals = np.array([(0, begin), (begin, end), (end, dur)])
    labels = np.array(
        [CLF_NON_TARGET_LABEL, CLF_TARGET_LABEL, CLF_NON_TARGET_LABEL],
        dtype="U16",
    )
    return (intervals, labels)


def multiChorusSections(intvs, dur):
    """avoid intersection of tuned intervals"""

    def key(x):
        # timestamp with precision of 0.01s
        return int(x * 100)

    # value 1=chorus begin -1=chorus end
    boundaries = defaultdict(int)
    for intv in intvs:
        boundaries[key(intv[0])] += 1
        boundaries[key(intv[1])] -= 1
    intervals, labels = [[0, 0]], [CLF_NON_TARGET_LABEL]
    state = 0  # 0:others >0:chorus
    for bdr in sorted(boundaries.keys()):
        t = bdr / 100.0
        intervals[-1][1] = t
        intervals.append([t, 0])
        state += boundaries[bdr]
        if state == 0:
            labels.append(CLF_NON_TARGET_LABEL)
        elif state > 0:
            labels.append(CLF_TARGET_LABEL)
        else:
            logger.error(f"invalid state, boundaries={boundaries}")
    intervals[-1][1] = dur
    mirexFmt = (np.array(intervals), np.array(labels, dtype="U16"))
    logger.debug(f"multi chorus sections, output=\n{mirexLines(mirexFmt)}")
    return mergeIntervals(mirexFmt)


def numberCliques(cliques, labels):
    # numbering cliques (recurrence label)
    typeCount = {}
    for clique in sorted(cliques, key=lambda c: c[0]):
        ltype = labels[clique[0]]
        count = typeCount.get(ltype, 0)
        for idx in clique:
            labels[idx] += f" {chr(65+count)}"
        typeCount[ltype] = count + 1
    return labels


def removeNumber(mirexFmt):
    intervals, labels = mirexFmt
    labels = np.array(list(map(lambda label: label.split()[0], labels)), dtype="U16")
    return (intervals, labels)


def printArray(arr, name, show=False):
    logger.debug(f"{name}{arr.shape}, min={np.min(arr)} max={np.max(arr)}")
    if show:
        plt.imshow(logSSM(arr), aspect="auto")
        plt.colorbar()
        plt.show()


def mirexLines(mirexFmt):
    intervals, labels = mirexFmt
    s = ""
    for intv, label in zip(intervals, labels):
        s += f"{intv} {label}\n"
    return s
