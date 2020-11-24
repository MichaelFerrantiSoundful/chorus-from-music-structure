import click
import pickle
from tqdm import tqdm
import os
import numpy as np
import matplotlib.pyplot as plt
from multiprocessing import Pool

from utility.dataset import Preprocess_Dataset, buildPreprocessDataset
from utility.transform import ExtractCliques, ExtractMel
from utility.algorithmsWrapper import (
    AlgoSeqRecur,
    GenerateSSM,
    GroudTruthStructure,
    MsafAlgos,
    MsafAlgosBdryOnly,
)
from models.classifier import GetAlgoData
from configs.configs import NUM_WORKERS, logger
from configs.trainingConfigs import (
    CHORUS_CLASSIFIER_TRAIN_DATA_FILE,
    CHORUS_CLASSIFIER_VAL_DATA_FILE,
    CLF_TRAIN_SET,
    CLF_VAL_SET,
    USING_DATASET,
)
from models.classifier import ChorusClassifier


def starGetCliqueClassData(t):
    getData, baseset, idx = t
    res = getData(baseset, idx)
    return res


def buildCCDataset(cpath, baseset, getData, force=True):
    if not os.path.exists(cpath) or force:
        X = []
        y = []
        logger.info(
            f"building clique class Data for <{baseset.__class__.__name__}> @ {cpath}"
        )
        with Pool(NUM_WORKERS) as p:
            N = len(baseset)
            results = list(
                tqdm(
                    p.imap(
                        starGetCliqueClassData,
                        zip([getData] * N, [baseset] * N, range(N)),
                    ),
                    total=N,
                )
            )
        for features, clabels in results:
            X.extend([feature for feature in features])
            y.extend([clabel for clabel in clabels])
        with open(cpath, "wb") as f:
            pickle.dump((X, y), f)


def testCCDataset(method):
    logger.info(f"testCC method:{method}")
    cpath_train = CHORUS_CLASSIFIER_TRAIN_DATA_FILE[method]
    cpath_val = CHORUS_CLASSIFIER_VAL_DATA_FILE[method]
    _clf = ChorusClassifier(cpath_train)
    _clf.train()
    clf = _clf.clf
    Xt, yt = _clf.loadData(cpath_val)
    with np.printoptions(precision=3, suppress=True):
        if hasattr(clf, "feature_importances_"):
            logger.info(
                f'feature importance, {[f"{s}={x*len(_clf.feature_names):.3f}" for x, s in sorted(zip(clf.feature_importances_, _clf.feature_names))]}'
            )
        logger.info(f"test classifier on valid data, score={clf.score(Xt, yt):.3f}")


# build Preprocess Dataset for feature extraction
transforms = {
    "extract-mel": ExtractMel(),
    "generate-ssm": GenerateSSM(dataset=USING_DATASET),
    "extract-cliques": ExtractCliques(dataset=USING_DATASET),
}
trainData = CHORUS_CLASSIFIER_TRAIN_DATA_FILE
methods = {
    "seqRecur": GetAlgoData(AlgoSeqRecur(trainData["seqRecur"])),
    "scluster": GetAlgoData(MsafAlgos("scluster", trainData["scluster"])),
    "cnmf": GetAlgoData(MsafAlgos("cnmf", trainData["cnmf"])),
    "sf": GetAlgoData(MsafAlgosBdryOnly("sf", trainData["sf"])),
    "olda": GetAlgoData(MsafAlgosBdryOnly("olda", trainData["olda"])),
    "foote": GetAlgoData(MsafAlgosBdryOnly("foote", trainData["foote"])),
    "gtBoundary": GetAlgoData(GroudTruthStructure(trainData["gtBoundary"])),
}


@click.group()
def cli():
    pass


@click.command()
@click.option(
    "--transform", nargs=1, type=click.Choice(transforms.keys()), default=None
)
@click.option("--force", nargs=1, type=click.BOOL, default=False)
def build(transform, force):
    buildTransforms = (
        transforms.values() if transform is None else [transforms[transform]]
    )

    for tf in buildTransforms:
        buildPreprocessDataset(USING_DATASET, tf, force=force)


@click.command()
@click.option("--method", nargs=1, type=click.Choice(methods.keys()), default=None)
def train(method):
    trainMethods = methods.items() if method is None else [(method, methods[method])]
    for name, getDataFun in trainMethods:
        cpath_train = CHORUS_CLASSIFIER_TRAIN_DATA_FILE[name]
        cpath_val = CHORUS_CLASSIFIER_VAL_DATA_FILE[name]
        buildCCDataset(cpath_train, CLF_TRAIN_SET, getDataFun)
        buildCCDataset(cpath_val, CLF_VAL_SET, getDataFun)
        testCCDataset(name)


cli.add_command(build)
cli.add_command(train)
if __name__ == "__main__":
    cli()
