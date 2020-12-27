"""
Programmer: Chris Tralie, 12/2016 (ctralie@alumni.princeton.edu)
Purpose: To provide tools for quickly computing all pairs self-similarity
and cross-similarity matrices
"""
import numpy as np
import matplotlib.pyplot as plt
import scipy.misc
from copy import copy
from scipy import sparse


def getCSM(X, Y):
    """
    Return the Euclidean cross-similarity matrix between the M points
    in the Mxd matrix X and the N points in the Nxd matrix Y.
    :param X: An Mxd matrix holding the coordinates of M points
    :param Y: An Nxd matrix holding the coordinates of N points
    :return D: An MxN Euclidean cross-similarity matrix
    """
    C = np.sum(X ** 2, 1)[:, None] + np.sum(Y ** 2, 1)[None, :] - 2 * X.dot(Y.T)
    C[C < 0] = 0
    return np.sqrt(C)


def getCSMCosine(X, Y):
    XNorm = np.sqrt(np.sum(X ** 2, 1))
    XNorm[XNorm == 0] = 1
    YNorm = np.sqrt(np.sum(Y ** 2, 1))
    YNorm[YNorm == 0] = 1
    # assert np.min(X) >= 0 and np.min(Y) >= 0, f"{np.min(X)} {np.min(Y)}"
    similarity = (X / XNorm[:, None]).dot((Y / YNorm[:, None]).T)
    similarity[similarity >= 1] = 1
    similarity[similarity <= -1] = -1
    # Make sure distance 0 is the same and distance 2 is the most different
    distance = 1 - similarity
    return distance
    # angularDistance = 4 * np.arccos(similarity) / np.pi
    # return angularDistance


def getShiftInvariantCSM(metricFunc, wins_per_block):
    def fun(X, Y):
        # X[m, n_class * wins]
        m, d = X.shape
        n_class = d // wins_per_block
        # Xr[m, n_class, wins]
        Xr = copy(X.reshape(m, n_class, wins_per_block))
        # Dlist[n_class, m, m]
        DList = []
        for shift in range(n_class):
            Xn = np.roll(Xr, shift, axis=1).reshape(m, d)
            D = metricFunc(Xn, Y)
            DList.append(D)
        DList = np.array(DList)
        # res[m, m]
        res = np.min(DList, axis=0)
        return res

    return fun
