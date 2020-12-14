import argparse

def gettrainargs():
    parser = argparse.ArgumentParser()
    parser.add_argument("-q", "--qmatrix", help="Use file as Q matrix")
    parser.add_argument("-v", "--vmatrix", help="Use file as V matrix")
    parser.add_argument("-p", "--plot", help="Plot the learned filters", action="store_true")
    parser.add_argument("-o", "--outdir", help="Output dir")
    parser.add_argument("--qangle", help="number of angles")
    parser.add_argument("--qstre", help="number of strength")
    parser.add_argument("--qcohe", help="number of coherence")
    parser.add_argument("--patchsize", help="patch size")
    parser.add_argument("--scale", help="scale factor")
    parser.add_argument("--fp", help="float precision")
    args = parser.parse_args()
    return args
