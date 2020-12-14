import cv2
import numpy as np
import os
import pickle
import sys
from cgls import cgls
from filterplot import filterplot
from gaussian2d import gaussian2d
from gettrainargs import gettrainargs
from hashkey import hashkey
from math import floor
from matplotlib import pyplot as plt
from scipy import interpolate
from skimage import transform
from scipy.signal import convolve2d
from os.path import basename, dirname, splitext

args = gettrainargs()

# Begin of define parameters
R = 2
patchsize = 11
gradientsize = 9
Qangle = 24
Qstrength = 3
Qcoherence = 3
trainpath = 'train'
fprecision = 32
outdir = 'trainResultFp32'

# End of define parameters
if args.fp:
    fprecision = int(args.fp)

precision = np.float64
if fprecision == 16:
    precision = np.float16
elif fprecision == 32:
    precision = np.float32
elif fprecision == 64:
    precision = np.float64
else:
    print('unsupported fprecision {}'.format(fprecision))
    exit(-1)

if args.outdir:
    outdir = args.outdir

convprecision = precision
if convprecision == np.float16:
    convprecision = np.float32

if Qstrength != 3:
    print('unsupported Qstrength {}'.format(Qstrength))
    exit(-1)

if Qcoherence != 3:
    print('unsupported Qcoherence {}'.format(Qcoherence))
    exit(-1)

print('Start training with configuration:')
print('   scale:\t{}'.format(R))
print('   patchsize:\t{}'.format(patchsize))
print('   Qangle:\t{}'.format(Qangle))
print('   Qstrength:\t{}'.format(Qstrength))
print('   Qcoherence:\t{}'.format(Qcoherence))
print('   trainpath:\t{}'.format(trainpath))
print('   fprecision:\t{}'.format(fprecision))
print('   outdir:\t{}'.format(outdir))

# Calculate the margin
maxblocksize = max(patchsize, gradientsize)
#margin = floor(maxblocksize/2)
patchmargin = floor(patchsize/2)
gradientmargin = floor(gradientsize/2)

Q = np.zeros((Qangle, Qstrength, Qcoherence, R*R, patchsize*patchsize, patchsize*patchsize), dtype=np.float64)
V = np.zeros((Qangle, Qstrength, Qcoherence, R*R, patchsize*patchsize), dtype=np.float64)
h = np.zeros((Qangle, Qstrength, Qcoherence, R*R, patchsize*patchsize), dtype=precision)

# Read Q,V from file
if args.qmatrix:
    with open(args.qmatrix, "rb") as fp:
        Q = pickle.load(fp)
if args.vmatrix:
    with open(args.vmatrix, "rb") as fp:
        V = pickle.load(fp)

# Matrix preprocessing
# Preprocessing normalized Gaussian matrix W for hashkey calculation
weighting = gaussian2d([gradientsize, gradientsize], 2)
weighting = np.diag(weighting.ravel()).astype(precision)

# Get image list
imagelist = []
for parent, dirnames, filenames in os.walk(trainpath):
    for filename in filenames:
        if filename.lower().endswith(('.bmp', '.dib', '.png', '.jpg', '.jpeg', '.pbm', '.pgm', '.ppm', '.tif', '.tiff')):
            imagelist.append(os.path.join(parent, filename))

if not os.path.exists(outdir):
    os.mkdir(outdir)

# pass1=quantization, pass2=ATA/ATb
def processImage(imgPath, passId):
    global R
    global Qangle
    global Qstrength
    global Qcoherence
    global strList
    global coheList
    global Q
    global V
    imgbasename = splitext(basename(image))[0]
    origin = cv2.imread(image)
    if False:
        cropw = origin.shape[1] // R * R
        croph = origin.shape[0] // R * R
        origin = origin[:croph, :cropw, :]
    # Extract only the luminance in YCbCr
    grayorigin = cv2.cvtColor(origin, cv2.COLOR_BGR2YCrCb)[:,:,0]
    # Normalized to [0,1]
    if False:
        grayorigin = cv2.normalize(grayorigin.astype('float'), None, grayorigin.min()/255, grayorigin.max()/255, cv2.NORM_MINMAX)
    else:
        grayorigin = grayorigin / 255.0
    # Downscale (bicubic interpolation)
    if False:
        height, width = grayorigin.shape
        LR = transform.resize(grayorigin, (floor((height+1)/2),floor((width+1)/2)), mode='reflect', anti_aliasing=False)
    else:
        LR = cv2.resize(grayorigin, ((origin.shape[1]+ 1) // R, (origin.shape[0]+ 1) // R), interpolation=cv2.INTER_CUBIC)
        LR = np.clip(LR, 0.0, 1.0)
    # Upscale (bilinear interpolation)
    if False:
        upscaledLR = cv2.resize(LR, (origin.shape[1], origin.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        height, width = LR.shape
        heightgrid = np.linspace(0, height-1, height)
        widthgrid = np.linspace(0, width-1, width)
        bilinearinterp = interpolate.interp2d(widthgrid, heightgrid, LR, kind='linear')
        heightgrid = np.linspace(0, height-1, height*R-1)
        widthgrid = np.linspace(0, width-1, width*R-1)
        upscaledLR = bilinearinterp(widthgrid, heightgrid)

    sobelx = (np.array([[-1, 0, 1],
            [-2, 0, 2],
            [-1, 0, 1]]) / 9.0).astype(convprecision)
    sobely = (np.array([[-1, -2, -1],
            [0, 0, 0],
            [1, 2, 1]]) / 9.0).astype(convprecision)
    im_gx = convolve2d(upscaledLR.astype(convprecision), sobelx, mode='same', boundary='fill').astype(precision)
    im_gy = convolve2d(upscaledLR.astype(convprecision), sobely, mode='same', boundary='fill').astype(precision)

    # Calculate A'A, A'b and push them into Q, V
    height, width = upscaledLR.shape
    # to align margins with OCL
    marginL = 8
    marginT = 8
    procw = (width - 16) // 16 * 16
    proch = (height - 16) // 16 * 16
    marginR = width - marginL - procw
    marginB = height - marginT - proch

    if passId == 2:
        hashDict = {}
        hashDict['angle'] = np.zeros((proch, procw), dtype=np.uint8)
        hashDict['stre'] = np.zeros((proch, procw), dtype=np.uint8)
        hashDict['cohe'] = np.zeros((proch, procw), dtype=np.uint8)
    
    for row in range(marginT, height-marginB):
        for col in range(marginL, width-marginR):
            # Get patch
            patch = upscaledLR[row-patchmargin:row+patchmargin+1, col-patchmargin:col+patchmargin+1]
            patch = np.matrix(patch.ravel()).astype(precision)
            # Get gradient block
            gy_block = im_gy[row-gradientmargin:row+gradientmargin+1, col-gradientmargin:col+gradientmargin+1]
            gx_block = im_gx[row-gradientmargin:row+gradientmargin+1, col-gradientmargin:col+gradientmargin+1]
            # Calculate hashkey
            angle, strength, coherence, theta, lamda, u = hashkey(gy_block, gx_block, Qangle, weighting, precision)
            if passId == 1:
                # store lamda, u
                strList.append(lamda)
                coheList.append(u)
            elif passId == 2:
                # Get pixel type
                pixeltype = ((row-marginT) % R) * R + ((col-marginL) % R)
                # Get corresponding HR pixel
                pixelHR = grayorigin[row,col]
                # Compute A'A and A'b
                ATA = np.dot(patch.T, patch).astype(precision)
                ATb = np.dot(patch.T, pixelHR).astype(precision)
                ATb = np.array(ATb).ravel().astype(precision)
                # Compute Q and V
                Q[angle,strength,coherence,pixeltype] += ATA.astype(np.float64)
                V[angle,strength,coherence,pixeltype] += ATb.astype(np.float64)
                # save to hashDict
                hashDict['angle'][row-marginT, col-marginL] = angle
                hashDict['stre'][row-marginT, col-marginL] = strength
                hashDict['cohe'][row-marginT, col-marginL] = coherence
    if passId == 2:
        # save LR and upscaledLR
        cv2.imwrite(os.path.join(outdir, imgbasename + '-LR.png'), (LR * 255.0).astype(np.uint8))
        cv2.imwrite(os.path.join(outdir, imgbasename + '-upscaledLR.png'), (upscaledLR * 255.0).astype(np.uint8))
        # save hash
        hashDict['angle'].dump(os.path.join(outdir, imgbasename + '-angle.p'))
        cv2.imwrite(os.path.join(outdir, imgbasename + '-angle.png'), (hashDict['angle'] * 255.0 / Qangle).astype(np.uint8))
        hashDict['stre'].dump(os.path.join(outdir, imgbasename + '-stre.p'))
        cv2.imwrite(os.path.join(outdir, imgbasename + '-stre.png'), (hashDict['stre'] * 255.0 / Qstrength).astype(np.uint8))
        hashDict['cohe'].dump(os.path.join(outdir, imgbasename + '-cohe.p'))
        cv2.imwrite(os.path.join(outdir, imgbasename + '-cohe.png'), (hashDict['cohe'] * 255.0 / Qcoherence).astype(np.uint8))

strList = []
coheList = []
# quantize strength and coherence
imagecount = 1
for image in imagelist:
    print('\r', end='')
    print(' ' * 60, end='')
    print('\rQuantizing image ' + str(imagecount) + ' of ' + str(len(imagelist)) + ' (' + image + ')')
    processImage(image, 1)
    imagecount += 1

length = len(strList)
print('collected {} str/cohe samples'.format(length))
strList.sort()
coheList.sort()
print('str min {}, max {}'.format(strList[0], strList[length-1]))
print('cohe min {}, max {}'.format(coheList[0], coheList[length-1]))
strSplitter = []
coheSplitter = []
for i in range(1, Qstrength):
    idx = length * i // Qstrength
    strSplitter.append(strList[idx])
for i in range(1, Qcoherence):
    idx = length * i // Qcoherence
    coheSplitter.append(coheList[idx])
print('quantized str splitter', strSplitter)
print('quantized cohe splitter', coheSplitter)

# Compute Q and V
imagecount = 1
for image in imagelist:
    print('\r', end='')
    print(' ' * 60, end='')
    print('\rProcessing image ' + str(imagecount) + ' of ' + str(len(imagelist)) + ' (' + image + ')')
    processImage(image, 2)
    imagecount += 1

# Write Q,V to file
with open(os.path.join(outdir, 'q.p'), "wb") as fp:
    pickle.dump(Q, fp)
with open(os.path.join(outdir, 'v.p'), "wb") as fp:
    pickle.dump(V, fp)

# Preprocessing permutation matrices P for nearly-free 8x more learning examples
print('\r', end='')
print(' ' * 60, end='')
print('\rPreprocessing permutation matrices P for nearly-free 8x more learning examples ...')
sys.stdout.flush()
P = np.zeros((patchsize*patchsize, patchsize*patchsize, 7))
rotate = np.zeros((patchsize*patchsize, patchsize*patchsize))
flip = np.zeros((patchsize*patchsize, patchsize*patchsize))
for i in range(0, patchsize*patchsize):
    i1 = i % patchsize
    i2 = floor(i / patchsize)
    j = patchsize * patchsize - patchsize + i2 - patchsize * i1
    rotate[j,i] = 1
    k = patchsize * (i2 + 1) - i1 - 1
    flip[k,i] = 1
for i in range(1, 8):
    i1 = i % 4
    i2 = floor(i / 4)
    P[:,:,i-1] = np.linalg.matrix_power(flip,i2).dot(np.linalg.matrix_power(rotate,i1))
Qextended = np.zeros((Qangle, Qstrength, Qcoherence, R*R, patchsize*patchsize, patchsize*patchsize), dtype=np.float64)
Vextended = np.zeros((Qangle, Qstrength, Qcoherence, R*R, patchsize*patchsize), dtype=np.float64)
for pixeltype in range(0, R*R):
    for angle in range(0, Qangle):
        for strength in range(0, Qstrength):
            for coherence in range(0, Qcoherence):
                for m in range(1, 8):
                    m1 = m % 4
                    m2 = floor(m / 4)
                    newangleslot = angle
                    if m2 == 1:
                        newangleslot = Qangle-angle-1
                    newangleslot = int(newangleslot-Qangle/2*m1)
                    while newangleslot < 0:
                        newangleslot += Qangle

                    newQ = P[:,:,m-1].T.dot(Q[angle,strength,coherence,pixeltype]).dot(P[:,:,m-1])
                    newV = P[:,:,m-1].T.dot(V[angle,strength,coherence,pixeltype])
                    Qextended[newangleslot,strength,coherence,pixeltype] += newQ.astype(np.float64)
                    Vextended[newangleslot,strength,coherence,pixeltype] += newV.astype(np.float64)
Q += Qextended
V += Vextended

# debug >>>
# Write Q,V to file
with open(os.path.join(outdir, 'q+.p'), "wb") as fp:
    pickle.dump(Q, fp)
with open(os.path.join(outdir, 'v+.p'), "wb") as fp:
    pickle.dump(V, fp)
# debug <<<

# Compute filter h
print('Computing h ...')
sys.stdout.flush()
operationcount = 0
totaloperations = R * R * Qangle * Qstrength * Qcoherence
for pixeltype in range(0, R*R):
    for angle in range(0, Qangle):
        for strength in range(0, Qstrength):
            for coherence in range(0, Qcoherence):
                if round(operationcount*100/totaloperations) != round((operationcount+1)*100/totaloperations):
                    print('\r|', end='')
                    print('#' * round((operationcount+1)*100/totaloperations/2), end='')
                    print(' ' * (50 - round((operationcount+1)*100/totaloperations/2)), end='')
                    print('|  ' + str(round((operationcount+1)*100/totaloperations)) + '%', end='')
                    sys.stdout.flush()
                operationcount += 1
                h[angle,strength,coherence,pixeltype] = cgls(Q[angle,strength,coherence,pixeltype].astype(np.float64), V[angle,strength,coherence,pixeltype].astype(np.float64)).astype(precision)

# Write filter to file
with open(os.path.join(outdir, 'filter.p'), "wb") as fp:
    pickle.dump(h, fp)

# Plot the learned filters
if args.plot:
    filterplot(h, R, Qangle, Qstrength, Qcoherence, patchsize, fprecision, outdir)

print('\r', end='')
print(' ' * 60, end='')
print('\rFinished.')
