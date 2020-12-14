import numpy as np
from math import atan2, floor, pi

def hashkey(gy, gx, Qangle, W, precision, strSplitter=None, coheSplitter=None):
    # Transform 2D matrix into 1D array
    gx = gx.ravel()
    gy = gy.ravel()

    # SVD calculation
    G = np.vstack((gx,gy)).T
    GTWG = G.T.dot(W).dot(G).astype(precision)

    ma = GTWG[0,0]
    mb = GTWG[0,1]
    mc = GTWG[1,0]
    md = GTWG[1,1]
    T = precision(ma + md)
    D = precision(ma * md - mb * mc)
    SQ = precision((T * T)/4 - D)
    if SQ < 0:
        if not np.isclose(SQ, 0, atol=1e-04):
            print('SQ={}'.format(SQ))
        SQ = 0
    L1 = precision(T/2 + np.sqrt(SQ))
    L2 = precision(T/2 - np.sqrt(SQ))
    if L1 < 0:
        if not np.isclose(L1, 0, atol=1e-04):
            print('L1={}'.format(L1))
        L1 = 0
    if L2 < 0:
        if not np.isclose(L2, 0, atol=1e-04):
            print('L1={}'.format(L2))
        L2 = 0

    try:
        theta = precision(atan2(mb, L1 - md))
    except:
        print('invalid eigen value:')
        print(' [{} {} {} {}]'.format(ma, mb, mc, md))
        print(' L1={}, L2={}'.format(T/2 + np.sqrt(SQ), T/2 - np.sqrt(SQ)))
        theta = 0.0

    if theta < 0:
        theta += pi

    lamda = precision(L1)
    try:
        sqrtlamda1 = np.sqrt(L1)
        sqrtlamda2 = np.sqrt(L2)
    except:
        print('L1={}, L2={}'.format(L1, L2))
        sqrtlamda1 = sqrtlamda2 = 0.0
    if sqrtlamda1 + sqrtlamda2 == 0:
        u = precision(0.0)
    else:
        u = precision((sqrtlamda1 - sqrtlamda2)/(sqrtlamda1 + sqrtlamda2))

    # Quantize
    angle = floor(theta/pi*Qangle)

    if strSplitter != None and len(strSplitter) == 2:
        str1 = strSplitter[0]
        str2 = strSplitter[1]
    else:
        str1 = 0.0001
        str2 = 0.001
    if lamda < str1:
        strength = 0
    elif lamda > str2:
        strength = 2
    else:
        strength = 1

    if coheSplitter != None and len(coheSplitter) == 2:
        cohe1 = coheSplitter[0]
        cohe2 = coheSplitter[1]
    else:
        cohe1 = 0.25
        cohe2 = 0.5
    if u < cohe1:
        coherence = 0
    elif u > cohe2:
        coherence = 2
    else:
        coherence = 1

    # Bound the output to the desired ranges
    if angle > 23:
        angle = 23
    elif angle < 0:
        angle = 0

    return angle, strength, coherence, theta, lamda, u
