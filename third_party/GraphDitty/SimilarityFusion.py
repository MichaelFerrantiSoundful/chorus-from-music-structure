"""
Programmer: Chris Tralie, 12/2016 (ctralie@alumni.princeton.edu)
Purpose: To implement similarity network fusion approach described in
[1] Wang, Bo, et al. "Unsupervised metric fusion by cross diffusion." Computer Vision and Pattern Recognition (CVPR), 2012 IEEE Conference on. IEEE, 2012.
[2] Wang, Bo, et al. "Similarity network fusion for aggregating data types on a genomic scale." Nature methods 11.3 (2014): 333-337.
"""
import numpy as np
import matplotlib.pyplot as plt
from scipy import sparse
import time
import os

from configs.configs import logger


def getW(D, K, Mu=0.5):
    """
    Return affinity matrix
    :param D: Self-similarity matrix
    :param K: Number of nearest neighbors
    :param Mu: Nearest neighbor hyperparameter (default 0.5)
    """
    # W(i, j) = exp(-Dij^2/(mu*epsij))
    DSym = 0.5 * (D + D.T)
    np.fill_diagonal(DSym, 0)

    Neighbs = np.partition(DSym, K + 1, 1)[:, 0 : K + 1]
    MeanDist = np.mean(Neighbs, 1) * float(K + 1) / float(K)  # Need this scaling
    # to exclude diagonal element in mean
    # Equation 1 in SNF paper [2] for estimating local neighborhood radii
    # by looking at k nearest neighbors, not including point itself
    Eps = MeanDist[:, None] + MeanDist[None, :] + DSym
    Eps = Eps / 3
    Denom = 2 * (Mu * Eps) ** 2
    Denom[Denom == 0] = 1
    W = np.exp(-(DSym ** 2) / Denom)
    return W


def getP(W, diagRegularize=False):
    """
    Turn a similarity matrix into a proability matrix,
    with each row sum normalized to 1
    :param W: (MxM) Similarity matrix
    :param diagRegularize: Whether or not to regularize
    the diagonal of this matrix
    :returns P: (MxM) Probability matrix
    """
    if diagRegularize:
        P = 0.5 * np.eye(W.shape[0])
        WNoDiag = np.array(W)
        np.fill_diagonal(WNoDiag, 0)
        RowSum = np.sum(WNoDiag, 1)
        RowSum[RowSum == 0] = 1
        P = P + 0.5 * WNoDiag / RowSum[:, None]
        return P
    else:
        RowSum = np.sum(W, 1)
        RowSum[RowSum == 0] = 1
        P = W / RowSum[:, None]
        return P


def getS(W, K):
    """
    Same thing as P but restricted to K nearest neighbors
        only (using partitions for fast nearest neighbor sets)
    (**note that nearest neighbors here include the element itself)
    :param W: (MxM) similarity matrix
    :param K: Number of neighbors to use per row
    :returns S: (MxM) S matrix
    """
    N = W.shape[0]
    J = np.argpartition(-W, K, 1)[:, 0:K]
    I = np.tile(np.arange(N)[:, None], (1, K))
    V = W[I.flatten(), J.flatten()]
    # Now figure out L1 norm of each row
    V = np.reshape(V, J.shape)
    SNorm = np.sum(V, 1)
    SNorm[SNorm == 0] = 1
    V = V / SNorm[:, None]
    [I, J, V] = [I.flatten(), J.flatten(), V.flatten()]
    S = sparse.coo_matrix((V, (I, J)), shape=(N, N)).tocsr()
    return S


def doSimilarityFusionWs(
    Ws,
    K=5,
    niters=20,
    reg_diag=1,
    reg_neighbs=0.5,
    verboseTimes=True,
):
    """
    Perform similarity fusion between a set of exponentially
    weighted similarity matrices
    :param Ws: An array of NxN affinity matrices for N songs
    :param K: Number of nearest neighbors
    :param niters: Number of iterations
    :param reg_diag: Identity matrix regularization parameter for
        self-similarity promotion
    :param reg_neighbs: Neighbor regularization parameter for promoting
        adjacencies in time
    :param PlotNames: Strings describing different similarity
        measurements for the animation
    :param PlotExtents: Time labels for images
    :return D: A fused NxN similarity matrix
    """
    tic = time.time()
    # Full probability matrices
    Ps = [getP(W) for W in Ws]
    # Nearest neighbor truncated matrices
    Ss = [getS(W, K) for W in Ws]

    # Now do cross-diffusion iterations
    Pts = [np.array(P) for P in Ps]
    nextPts = [np.zeros(P.shape) for P in Pts]
    if verboseTimes:
        logger.debug("Time getting Ss and Ps: %g" % (time.time() - tic))

    N = len(Pts)
    AllTimes = []
    for it in range(niters):
        ticiter = time.time()
        for i in range(N):
            nextPts[i] *= 0
            tic = time.time()
            for k in range(N):
                if i == k:
                    continue
                nextPts[i] += Pts[k]
            nextPts[i] /= float(N - 1)

            # Need S*P*S^T, but have to multiply sparse matrix on the left
            tic = time.time()
            A = Ss[i].dot(nextPts[i].T)
            nextPts[i] = Ss[i].dot(A.T)
            toc = time.time()
            AllTimes.append(toc - tic)
            if reg_diag > 0:
                nextPts[i] += reg_diag * np.eye(nextPts[i].shape[0])
            if reg_neighbs > 0:
                arr = np.arange(nextPts[i].shape[0])
                [I, J] = np.meshgrid(arr, arr)
                # Add diagonal regularization as well
                nextPts[i][np.abs(I - J) == 1] += reg_neighbs

        Pts = nextPts
        if verboseTimes:
            logger.debug(
                "Elapsed Time Iter %i of %i: %g"
                % (it + 1, niters, time.time() - ticiter)
            )
    if verboseTimes:
        logger.debug("Total Time multiplying: %g" % np.sum(np.array(AllTimes)))
    FusedScores = np.zeros(Pts[0].shape)
    for Pt in Pts:
        FusedScores += Pt
    return FusedScores / N
