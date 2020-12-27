import librosa
import scipy
import numpy as np
from copy import deepcopy

from third_party.GraphDitty.CSMSSMTools import (
    getCSM,
    getCSMCosine,
    getShiftInvariantCSM,
)
from third_party.GraphDitty.SimilarityFusion import doSimilarityFusionWs, getW
from utility.common import logSSM, printArray
from configs.modelConfigs import (
    PITCH_CHROMA_CLASS,
    PITCH_CHROMA_HOP,
    PITCH_CHROMA_COUNT,
    REC_SMOOTH,
)
from configs.configs import logger


def selfSimilarityMatrix(
    wavfile,
    mel=None,
    win_fac=10,
    wins_per_block=20,
    K=5,
    sr=22050,
    hop_length=512,
):
    logger.debug(f"loading:{wavfile}")
    y, sr = librosa.load(wavfile, sr=sr)
    nHops = (y.size - hop_length * (win_fac - 1)) / hop_length
    intervals = np.arange(0, nHops + 1e-6, win_fac).astype(int)
    logger.debug(
        f"nHops={nHops}=(size-hop_length*(win_fac-1))/hop_length=({y.size} - {hop_length}*({win_fac}-1))/{hop_length} intvs={intervals[-1]}"
    )
    # chorma
    chroma = librosa.feature.chroma_cqt(
        y=y, sr=sr, hop_length=hop_length, bins_per_octave=12 * 3
    )
    # mfcc
    S = librosa.feature.melspectrogram(y, sr=sr, n_mels=128, hop_length=hop_length)
    log_S = librosa.power_to_db(S, ref=np.max)
    mfcc = librosa.feature.mfcc(S=log_S, n_mfcc=20)
    lifterexp = 0.6
    coeffs = np.arange(mfcc.shape[0]) ** lifterexp
    coeffs[0] = 1
    mfcc = coeffs[:, None] * mfcc
    # tempogram
    SUPERFLUX_SIZE = 5
    oenv = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=hop_length, max_size=SUPERFLUX_SIZE
    )
    tempogram = librosa.feature.tempogram(
        onset_envelope=oenv, sr=sr, hop_length=hop_length
    )

    # generate W- matrices
    n_frames = np.min([chroma.shape[1], mfcc.shape[1], tempogram.shape[1]])
    intervals = librosa.util.fix_frames(intervals, x_min=0, x_max=n_frames)
    times = intervals * float(hop_length) / float(sr)
    size = n_frames // win_fac
    logger.debug(
        f"frames fixed, intervals={intervals[-1]} hop={intervals[1]-intervals[0]} size={size}"
    )
    WMfcc = feature2W(mfcc, size, np.mean, getCSM, wins_per_block=wins_per_block)
    WChroma = feature2W(
        chroma,
        size,
        np.median,
        getShiftInvariantCSM(getCSMCosine, wins_per_block),
        wins_per_block=wins_per_block,
    )
    WTempo = feature2W(tempogram, size, np.mean, getCSM, wins_per_block=wins_per_block)
    printArray(WMfcc, "mfcc")
    printArray(WChroma, "chorma")
    printArray(WTempo, "tempo")

    # melody
    if mel is not None:
        _, pitches = mel
        pitches = pitchChroma(pitches)
        WPitches = feature2W(
            pitches,
            size,
            np.median,
            getShiftInvariantCSM(getCSMCosine, wins_per_block),
            wins_per_block=wins_per_block,
        )
        printArray(WPitches, "pitchChroma")
        Ws = [WMfcc, WChroma, WPitches, WTempo]
    else:
        Ws = [WMfcc, WChroma, WTempo]

    if REC_SMOOTH > 0:
        df = librosa.segment.timelag_filter(scipy.ndimage.median_filter)
        Ws = [df(W, size=(1, REC_SMOOTH)) for W in Ws]
    W = doSimilarityFusionWs(Ws, K=K, niters=3, reg_diag=1.0, reg_neighbs=0.5)
    printArray(W, "fused W")
    res = {
        "Ws": {
            "Fused": W,
            "Melody": WPitches if mel is not None else None,
        },
        "times": times,
    }
    return res


def pitchChroma(
    pitches,
    n_class=PITCH_CHROMA_CLASS,
    count=PITCH_CHROMA_COUNT,
    hop=PITCH_CHROMA_HOP,
):
    """input: [frames]
    output: [n_class, frames]"""
    pitches = deepcopy(pitches)
    frames = pitches.shape[-1]
    nonVoice = pitches <= 0  # whether it's a voicing frame
    pitches[nonVoice] = 10  # avoid log(0) warning
    pitches = librosa.hz_to_midi(pitches) * n_class / 12
    pitches = np.remainder(pitches.astype(int), n_class)
    # -1 represnets non-voice, will be ignored in bincount
    pitches[nonVoice] = n_class
    # pitches: [1, frames]
    pitches = np.expand_dims(pitches, axis=0)

    assert (pitches <= n_class).all()
    # XPitches: [count, frames]
    XPitches = librosa.feature.stack_memory(
        pitches, n_steps=count, delay=hop, mode="edge"
    )
    assert (XPitches <= n_class).all(), "suprise! just try again the bug might gone"

    # res: [n_class, frames]
    res = np.zeros((n_class, frames))
    weights = np.array([count - i for i in range(count)])
    for t in range(frames):
        bins = np.bincount(XPitches[:, t], weights=weights, minlength=n_class)
        res[:, t] = bins[:n_class]
    return res


def resize(feature, size):
    # feature[<dim>, <frames>]
    length = feature.shape[-1]
    hop = length // (size - 1)
    intervals = np.arange(0, length, hop).astype(int)
    intervals = librosa.util.fix_frames(intervals, x_min=0, x_max=hop * (size - 1))
    return intervals


def feature2W(feature, size, aggregator, simFunction, wins_per_block=20, K=5):
    intervals = resize(feature, size)
    # feature[<dim>, <frame>] -> [<dim>, <interval number>], intervals=frames//(size-1)
    feature = librosa.util.sync(feature, intervals, aggregate=aggregator)
    # Xfeature[<interval number>, <dim>*<wins_per_block>]
    Xfeature = librosa.feature.stack_memory(
        feature, n_steps=wins_per_block, mode="edge"
    ).T
    Dfeature = simFunction(Xfeature, Xfeature)
    # Wfeature[<interval number>, <interval number>]
    Wfeature = getW(Dfeature, K)
    assert not np.isnan(np.sum(Wfeature)), f"invalid affinity, Dfeature={Dfeature}"
    logger.debug(
        f"shapes, feature{feature.shape} Xfeature{Xfeature.shape} Wfeature{Wfeature.shape}"
    )
    return Wfeature
