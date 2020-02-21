import inspect
import numpy as np
from utils.commonUtils import sVT
from utils.commonUtils import is_numeric
from utils.commonUtils import fastUnique
from utils.commonUtils import queryIfColumnsVary
from utils.commonUtils import queryIfOnlyTwoUniqueRows
from utils.ccfUtils import regCCA_alt
from utils.ccfUtils import random_feature_expansion
from utils.ccfUtils import genFeatureExpansionParameters
from component_analysis import componentAnalysis
from twopoint_max_marginsplit import twoPointMaxMarginSplit

import logging
logger  = logging.getLogger(__name__)

def setupLeaf(YTrain, bReg, options):
    """
    Update tree struct to make node a leaf
    """
    tree = {}
    tree["bLeaf"]   = True
    tree["Npoints"] = YTrain.shape[0]
    tree["mean"]    = np.mean(YTrain, axis=0)

    if bReg:
        tree["std_dev"] = np.std(YTrain, axis=0, ddof=1)
        # If a mapping has been applied, invert it
        if not (options["org_stdY"].size == 0):
            tree["mean"] = tree["mean"] * options["org_stdY"]
            tree["std_dev"] = tree["std_dev"] * options["org_stdY"]

        if not (options["org_muY"].size == 0):
            tree["mean"] = tree["mean"] + options["org_muY"]

    return tree

def makeExpansionFunc(wZ, bZ, bIncOrig):
    if bIncOrig:
        f = lambda x: np.concatenate((x, random_feature_expansion(x, wZ, bZ)))
    else:
        f = lambda x: random_feature_expansion(x, wZ, bZ)

    return f

def calc_mse(cumtotal, cumsq, YTrainSort):
    value = np.divide(cumsq, (np.arange(0:YTrainSort.shape[0])).T) -\
            np.divide((cumtotal[0:-1, :]**2  + YTrainSort**2 + 2*cumtotal[0:-1, :] * YTrainSort),\
                      (np.arange(0:YTrainSort.shape[0]**2)).T)

    return value

#-------------------------------------------------------------------------------
def growCCT(XTrain, YTrain, bReg, options, iFeatureNum, depth):
    """
    This function applies greedy splitting according to the CCT algorithm and the
    provided options structure. Algorithm either returns a leaf or forms an
    internal splitting node in which case the function recursively calls itself
    for each of the children, eventually returning the corresponding subtree.

    Parameters
    ----------
    XTrain      = Array giving training features.  Data should be
                  processed using processInputData before being passed to
                  CCT
    YTrain      = Output data after formatting carried out by genCCF
    bReg        = Whether to perform regression instead of classification.
                  Default = false (i.e. classification).
    options     = Options class of type optionsClassCCF.  Some fields are
                  updated during recursion
    iFeatureNum = Grouping of features as per processInputData.  During
                  recursion if a feature is found to be identical across
                  data points, the corresponding values in iFeatureNum are
                  replaced with NaNs.
    depth       = Current tree depth (zero based)


    Returns
    -------
    tree        = Structure containing learnt tree
    """
    # Set any missing required variables
    if (options["mseTotal"]).size == 0:
        options["mseTotal"] = YTrain.var(axis=0)

    #---------------------------------------------------------------------------
    # First do checks for whether we should immediately terminate
    #---------------------------------------------------------------------------
    N = XTrain.shape[0]
    # Return if one training point, pure node or if options for returning
    # fulfilled.  A little case to deal with a binary YTrain is required.
    bStop = (N < (np.amax([2, options["minPointsForSplit"], 2 * options["minPointsLeaf"]]))) or\
            (is_numeric(options["maxDepthSplit"]) and depth > options["maxDepthSplit"])

    if depth > 490 and strcmpi(options["maxDepthSplit"], 'stack'):
        bStop = True
        logging.warning('Reached maximum depth imposed by stack limitations!')

    if bStop:
        tree = setupLeaf(YTrain, bReg, options)
        return tree

    elif:
        # Check class variation
        sumY = np.sum(YTrain, axis=0)
        bYVaries = (sumY ~= 0) and (sumY ~= N)
        if ~(np.any(bYVaries)):
            tree = setupLeaf(YTrain,bReg,options);
            return tree

    else:
        # Check if variance in Y is less than the cut off amount
         varY = YTrain.var(axis=0)
         if np.all(varY < (options["mseTotal"] * options["mseErrorTolerance"])):
             tree = setupLeaf(YTrain, bReg, options)
             return tree

    #---------------------------------------------------------------------------
    # Subsample features as required for hyperplane sampling
    #---------------------------------------------------------------------------
    iCanBeSelected = fastUnique(X=iFeatureNum)
    iCanBeSelected[np.isnan(iCanBeSelected)] = []
    lambda_   = min(len(iCanBeSelected), options["lambda"])
    indFeatIn = np.random.randint(low=0, high=iCanBeSelected.size, size=lambda_)
    iFeatIn   = iCanBeSelected[indFeatIn]

    bInMat = np.equal(sVT(X=iFeatureNum.flatten()), np.sort(iFeatIn.flatten()))

    iIn = (np.any(bInMat, axis=0)).ravel().nonzero()[0][0]

    # Check for variation along selected dimensions and
    # resample features that have no variation
    bXVaries = queryIfColumnsVary(X=XTrain[:, iIn], tol=options["XVariationTol"])

    if not np.all(bXVaries):
        iInNew = iIn
        nSelected = 0
        iIn = iIn[bXVaries]

        while not all(bXVaries) and lambda_ > 0:
            iFeatureNum[iInNew[~bXVaries]] = np.nan
            bInMat[:, iInNew[~bXVaries]] = False
            bRemainsSelected = np.any(bInMat, aixs=1)
            nSelected = nSelected + bRemainsSelected.sum(axis=0)
            iCanBeSelected[indFeatIn] = []
            lambda_   = min(iCanBeSelected.size, options["lambda"]-nSelected)
            if lambda_ < 1:
                break
            indFeatIn = np.random.randint(low=0, high=iCanBeSelected.size, size=lambda_)
            iFeatIn   = iCanBeSelected[indFeatIn]
            bInMat    = np.equal(sVT(X=iFeatureNum.flatten()), np.sort(iFeatIn.flatten()))
            iInNew    = (np.any(bInMat, axis=0)).ravel().nonzero()[0][0]
            bXVaries  = queryIfColumnsVary(X=XTrain[:, iInNew], tol=options["XVariationTol"])
            iInNew    = np.sort(np.concatenate(iIn, iInNew[bXVaries]))

    if iIn.size == 0:
        # This means that there was no variation along any feature, therefore exit.
        tree = setupLeaf(YTrain, bReg, options)
        return tree

    #---------------------------------------------------------------------------
    # Projection bootstrap if required
    #---------------------------------------------------------------------------
    if options["bProjBoot"]:
        iTrainThis = np.random.randint(N, size=(N,1))
        XTrainBag  = XTrain[iTrainThis, iIn]
        YTrainBag  = YTrain[iTrainThis, :]
    else:
        XTrainBag = XTrain[:, iIn]
        YTrainBag = YTrain

    bXBagVaries = queryIfColumnsVary(X=XTrainBag, tol=options["XVariationTol"])

    if not np.any(bXBagVaries) or\
        (not bReg and YTrainBag.shape[1] > 1  and (np.sum(np.absolute(np.sum(YTrainBag, axis=0)) > 1e-12) < 2)) or\
        (not bReg and YTrainBag.shape[1] == 1 and np.any(np.sum(YTrainBag, axis=0) == [0, YTrainBag.shape[0]])) or\
        (bReg and np.all(var(YTrainBag) < (options["mseTotal"] * options["mseErrorTolerance"]))):
        if not options["bContinueProjBootDegenerate"]:
            tree = setupLeaf(YTrain, bReg, options)
            return tree
        else:
            XTrainBag = XTrain[:, iIn]
            YTrainBag = YTrain

    #---------------------------------------------------------------------------
    # Check for only having two points
    #---------------------------------------------------------------------------
    if (not (options["projection"].size == 0)) and ((XTrainBag.shape[0] == 1) or queryIfOnlyTwoUniqueRows(X=XTrainBag)):
        bSplit, projMat, partitionPoint = twoPointMaxMarginSplit(XTrainBag, YTrainBag, options["XVariationTol"])
        if not bSplit:
            tree = setupLeaf(YTrain, bReg, options)
            return tree

        else:
            bLessThanTrain = (XTrain[:, iIn] * projMat) <= partitionPoint
            iDir = 1
    else:
        # Generate the new features as required
        if options["bRCCA"]:
            wZ, bZ  = genFeatureExpansionParameters(XTrainBag, options["rccaNFeatures"], options["rccaLengthScale"])
            fExp    = makeExpansionFunc(wZ, bZ, options["rccaIncludeOriginal"])
            projMat, _, _ = regCCA_alt(XTrainBag, YTrainBag, options["rccaRegLambda"], options["rccaRegLambda"], 1e-8)
            if projMat.size == 0:
                projMat = np.ones((XTrainBag.shape[1], 1))
            UTrain = fExp(XTrain[:, iIn]) @ projMat

        else:
            projMat, yprojMat, _, _, _ = componentAnalysis(XTrainBag, YTrainBag, options["projections"], options["epsilonCCA"])
            UTrain = XTrain[:, iIn] @ projMat

        #-----------------------------------------------------------------------
        # Choose the features to use
        #-----------------------------------------------------------------------

        # This step catches splits based on no significant variation
        bUTrainVaries = queryIfColumnsVary(UTrain, options["XVariationTol"])

        if not np.any(bUTrainVaries):
            tree = setupLeaf(YTrain,bReg,options);

        UTrain  = UTrain[:, bUTrainVaries]
        projMat = projMat[:, bUTrainVaries]

        if options["bUseOutputComponentsMSE"] and bReg and (YTrain.shape[1] > 1) and\
           (not (yprojMat.size == 0)) and (options["splitCriterion"] == 'mse'):
           VTrain = YTrain @ yprojMat

        #-----------------------------------------------------------------------
        # Search over splits using provided method
        #-----------------------------------------------------------------------
        nProjDirs = UTrain.shape[1]
        splitGains = np.empty((nProjDirs,1))
        splitGains.fill(np.nan)
        iSplits = np.empty((nProjDirs,1))
        iSplits.fill(np.nan)

        for nVarAtt in range(nProjDirs):
            # Calculate the probabilities of being at each class in each of child
            # nodes based on proportion of training data for each of possible
            # splits using current projection
            UTrainSort    = np.sort(UTrain[:, nVarAtt])
            iUTrainSort   = np.argsort(UTrain[:, nVarAtt])
            bUniquePoints = np.concatenate((np.diff(UTrainSort, n=1, axis=0)) > options["XVariationTol"], False))

            if options["bUseOutputComponentsMSE"] and bReg and YTrain.shape[1] > 1 and (not (yprojMat.size == 0)) and (options["splitCriterion"] == 'mse'):
                VTrainSort = VTrain[iUTrainSort, :]
            else:
                VTrainSort = YTrain[iUTrainSort, :]

            leftCum = np.cumsum(VTrainSort, axis=0)
            if YTrain.shape[1] ==1 or options["bSepPred"] and (not bReg):
                # Convert to [class_doesnt_exist,class_exists]
                leftCum = np.concatenate((np.subtract(sVT(X=np.arange(0,N)), leftCum), leftCum))

            rightCum = np.concatenate((np.subtract(leftCum[-1, :], leftCum)))

            # Calculate the metric values of the current node and two child nodes
            if not bReg:
                pL = np.divide(leftCum,  sVT(X=np.arange(0,N)))
                pR = np.divide(rightCum, sVT(X=np.arange(N-1, -1, -1)))

                split_criterion = options["splitCriterion"]
                if split_criterion == 'gini':
                    # Can ignore the 1 as this cancels in the gain
                    lTerm = -pL**2
                    rTerm = -pR**2
                elif split_criterion =='info':
                    lTerm = np.multiply(-pL, np.log2(pL))
                    lTerm[pL==0] = 0
                    rTerm = np.multiply(-pR, np.log2(pL))
                    rTerm[pR==0] = 0
                 else:
                     assert (True), 'Invalid split criterion!'

                if YTrain.shape[1] == 1 || options["bSepPred"]:
                    # Add grouped terms back together
                    end = YTrain.shape[1]
                    lTerm = lTerm[:, 0:end//2] + lTerm[:, end//2:end]
                    rTerm = rTerm[:, 0:end//2] + rTerm[:, end//2:end]

                if (not is_numeric(options["taskWeights"])) and (not options["multiTaskGainCombination"] == 'max'):
                    # No need to do anything fancy in the metric calculation
                    metricLeft  = np.sum(lTerm, axis=1)
                    metricRight = np.sum(rTerm, axis=1)
                else:
                    # Need to do grouped sums for each of the outputs as will be
                    # doing more than a simple averaging of there values
                   metricLeft = np.cumsum(lTerm, axis=1)
                   taskidxs = np.concatenate((options.task_ids(2:end)-1, end))
                   metricLeft = metricLeft[:, [options["task_ids"][2:end)-1,end]] -
                                 [np.zeros(size(metricLeft,1),1),metricLeft(:,options.task_ids(2:end)-1)];
                   metricRight = np.cumsum(rTerm, axis=1)
                   metricRight = metricRight(:,[options.task_ids(2:end)-1,end])-...
                       [zeros(size(metricRight,1),1),metricRight(:,options.task_ids(2:end)-1)];

            else:
                if options["splitCriterion"] == 'mse':
                    cumSqLeft = np.cumsum(VTrainSort**2)
                    varData   = np.subtract((cumSqLeft[-1,:]/N), ((leftCum[end, :]/N)**2))
                    if np.all(varData < (options["mseTotal"] * options["mseErrorTolerance"])):
                        # Total variation is less then the allowed tolerance so
                        # terminate and construct a leaf
                        tree = setupLeaf(YTrain, bReg, options);
                        return tree

                    metricLeft = calc_mse([zeros(1,size(VTrainSort,2));leftCum],cumSqLeft,VTrainSort);
                    # For calculating the right need to go in additive order again
                    # so go from other end and then flip
                    metricRight = [zeros(1,size(VTrainSort,2));...
                        calc_mse(rightCum(end:-1:1,:),...
                        bsxfun(@minus,cumSqLeft(end,:),cumSqLeft(end-1:-1:1,:)),...
                        VTrainSort(end:-1:2,:))];

                    metricRight = metricRight[-1:0:-1, :]
                    # No need to do the grouping for regression as each must be
                    # a seperate output anyway.

                else:
                    assert (True), 'Invalid split criterion!'

            metricCurrent = metricLeft[end,:]
            metricLeft[~bUniquePoints, :] = np.inf
            metricRight[~bUniquePoints,:] = np.inf

            # Calculate gain in metric for each of possible splits based on current
            # metric value minus metric value of child weighted by number of terms
            # in each child
            metricGain = np.subtract(metricCurrent, (np.multiply(sVT(X=np.arange(0,N)), metricLeft) + np.multiply(sVT(X=N-1:-1:0), metricRight))/N)

            # Combine gains if there are mulitple outputs.  Note that for gini,
            # info and mse, the joint gain is equal to the mean gain, hence
            # taking the mean here rather than explicitly calculating joints before.
            if metricGain.shape[1] > 1:
                if is_numeric(options["taskWeights"]):
                    # If weights provided, weight task appropriately in terms of importance.
                    metricGain = np.multiply(metricGain, sVT(X=options["taskWeights"].flatten()))

                multiTGC = options["multiTaskGainCombination"]
                if multiTGC == 'mean':
                    metricGain = np.mean(metricGain, axis=1)
                elif multiTGC == 'max'
                    metricGain = np.max(metricGain, axis=1)
                else:
                    assert (True), 'Invalid option for options.multiTaskGainCombination'

                # Disallow splits that violate the minimum number of leaf points
                end = metricGain.shape[0]
                metricGain[0:(options["minPointsLeaf"]-1)] = -np.inf;
                metricGain[(end-(options["minPointsLeaf"]-1)):] = -np.inf; # Note that end is never chosen anyway

                # Randomly sample from equally best splits
                iSplits[nVarAtt]    = np.argmax(metricGain[0:-1])
                splitGains[nVarAtt] = np.max(metricGain[0:-1])
                iEqualMax = (np.absolute(metricGain[0:-1] - splitGains[nVarAtt]) < (10*eps)).ravel().nonzero()
                if iEqualMax.size == 0:
                    iEqualMax = 1
                iSplits[nVarAtt] = iEqualMax[np.random.randint(iEqualMax.size)]

        # If no split gives a positive gain then stop
        if np.max(splitGains) < 0:
            tree = setupLeaf(YTrain, bReg, options)
            return tree

        # Establish between projection direction
        maxGain   = np.max(splitGains)
        iEqualMax = (np.absolute(splitGains - maxGain) < (10 * eps)).ravel().nonzero()
        # Use given method to break ties
        if options["dirIfEqual"] == 'rand':
            iDir = iEqualMax[np.random.randint(iEqualMax.size)]
        elif options["dirIfEqual"] == 'first':
            iDir = iEqualMax[0]
        else:
            assert (True), 'invalid dirIfEqual!'
        iSplit = iSplits[iDir]

        #-----------------------------------------------------------------------
        # Establish partition point and assign to child
        #-----------------------------------------------------------------------
        UTrain = UTrain[:, iDir]
        UTrainSort = np.sort(UTrain)

        # The convoluted nature of the below is to avoid numerical errors
        uTrainSortLeftPart = UTrainSort[iSplit]
        UTrainSort     = UTrainSort - uTrainSortLeftPart
        partitionPoint = UTrainSort[iSplit]*0.5 + UTrainSort[iSplit+1]*0.5
        partitionPoint = partitionPoint + uTrainSortLeftPart
        UTrainSort     = UTrainSort + uTrainSortLeftPart

        bLessThanTrain = (UTrain <= partitionPoint)

        if (not np.any(bLessThanTrain)) or np.all(bLessThanTrain):
            assert (True), 'Suggested split with empty!'

        #-----------------------------------------------------------------------
        # Recur tree growth to child nodes and constructs tree struct
        #-----------------------------------------------------------------------
        tree = {}
        tree["bLeaf"]   = False
        tree["Npoints"] = N
        tree["mean"]    = np.mean(YTrain, axis=0)

        if bReg:
            if (not options["org_stdY"].size == 0):
                tree["mean"] = tree["mean"] * options["org_stdY"]

            if (not options["org_muY"].size == 0):
                tree["mean"] = tree["mean"] + options["org_muY"]

        treeLeft  = growCCT(XTrain[bLessThanTrain, :], YTrain[bLessThanTrain,  :], bReg, options, iFeatureNum, depth+1)
        treeRight = growCCT(XTrain[~bLessThanTrain,:], YTrain[~bLessThanTrain, :], bReg, options, iFeatureNum, depth+1)
        tree["iIn"] = iIn

        # Ensure variable is defined
        try:
            x
        except NameError:
            x = None

        if options["bRCCA"]:
            try:
                if inspect.isfunction(fExp):
                    tree["featureExpansion"] = fExp
            except NameError:
                pass

        tree["decisionProjection"] = projMat[:, iDir]
        tree["paritionPoint"]      = partitionPoint
        tree["lessthanChild"]      = treeLeft
        tree["greaterthanChild"]   = treeRight

        return tree
