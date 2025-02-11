#!/usr/bin/env python3
# -*- coding: utf-8 -*-
##
# @file     test_siso_classification.py
# @author   Kyeong Soo (Joseph) Kim <kyeongsoo.kim@gmail.com>
# @date     2018-02-12
#
# @brief Testing a scalable indoor localization system (up to reference points)
#        based on Wi-Fi fingerprinting using a single-input and single-output
#        (SIMO) deep neural network (DNN) model for multi-class classification
#        of building, floor, and reference point.
#
# @remarks The results will be published in a paper submitted to the <a
#          href="http://www.sciencedirect.com/science/journal/08936080">Elsevier
#          Neural Networks</a> journal.

### import basic modules and a model to test
import os
os.environ['PYTHONHASHSEED'] = '0'  # for reproducibility
import platform
if platform.system() == 'Windows':
    data_path = os.path.expanduser(
        '~kks/Research/Ongoing/localization/xjtlu_surf_indoor_localization/data/UJIIndoorLoc'
    )
    module_path = os.path.expanduser(
        '~kks/Research/Ongoing/localization/elsevier_nn_scalable_indoor_localization/program/models'
    )
else:
    data_path = os.path.expanduser(
        '~kks/research/ongoing/localization/xjtlu_surf_indoor_localization/data/UJIIndoorLoc'
    )
    module_path = os.path.expanduser(
        '~kks/research/ongoing/localization/elsevier_nn_scalable_indoor_localization/program/models'
    )
import sys
sys.path.insert(0, module_path)
from siso_classification import siso_classification
### import other modules; keras and its backend will be loaded later
import argparse
import datetime
import numpy as np
import pandas as pd
import pathlib
import random as rn
from sklearn.preprocessing import StandardScaler
from time import time
from timeit import default_timer as timer
### import keras and its backend (e.g., tensorflow)
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"  # see issue #152
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # supress warning messages
import tensorflow as tf
session_conf = tf.ConfigProto(
    intra_op_parallelism_threads=1, inter_op_parallelism_threads=1
)  # force TF to use single thread for reproducibility
from keras import backend as K
# from keras.callbacks import TensorBoard
from keras.wrappers.scikit_learn import KerasClassifier
from sklearn.model_selection import cross_val_score, KFold, GridSearchCV

### global variables
training_data_file = data_path + '/' + 'trainingData2.csv'  # '-110' for the lack of AP.
validation_data_file = data_path + '/' + 'validationData2.csv'  # ditto

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-G",
        "--gpu_id",
        help=
        "ID of GPU device to run this script; default is 0; set it to a negative number for CPU (i.e., no GPU)",
        default=0,
        type=int)
    parser.add_argument(
        "-R", "--random_seed", help="random seed", default=0, type=int)
    parser.add_argument(
        "-E",
        "--epochs",
        help="number of epochs; default is 50",
        default=50,
        type=int)
    parser.add_argument(
        "-B",
        "--batch_size",
        help="batch size; default is 32",
        default=32,
        type=int)
    parser.add_argument(
        "-H",
        "--hidden_layers",
        help=
        "comma-separated numbers of units in hidden layers; default is '128,128'",
        default='128,128',
        type=str)
    parser.add_argument(
        "-O",
        "--optimizer",
        help="optimizer; default is 'adam'",
        default='adam',
        type=str)
    parser.add_argument(
        "-D",
        "--dropout",
        help="dropout rate before and after hidden layers; default is 0.0",
        default=0.0,
        type=float)
    parser.add_argument(
        "-F",
        "--frac",
        help=
        "fraction of the input data for hyperparameter search; default is 0.1",
        default=0.1,
        type=float)
    parser.add_argument(
        "-V",
        "--verbose",
        help=
        "verbosity mode: 0 = silent, 1 = progress bar, 2 = one line per epoch; default is 1",
        default=1,
        type=int)
    args = parser.parse_args()

    # set variables using command-line arguments
    gpu_id = args.gpu_id
    random_seed = args.random_seed
    epochs = args.epochs
    batch_size = args.batch_size
    if args.hidden_layers == '':
        hidden_layers = ''
    else:
        hidden_layers = [int(i) for i in (args.hidden_layers).split(',')]
    optimizer = args.optimizer
    dropout = args.dropout
    frac = args.frac
    verbose = args.verbose

    ### initialize numpy, random, TensorFlow, and keras
    np.random.seed(random_seed)
    rn.seed(random_seed)
    tf.set_random_seed(random_seed)
    if gpu_id >= 0:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = ''
    sess = tf.Session(
        graph=tf.get_default_graph(),
        config=session_conf)  # for reproducibility
    K.set_session(sess)

    ### load and pre-process the dataset
    training_df = (pd.read_csv(training_data_file, header=0)).sample(
        frac=frac)  # pass header=0 to be able to replace existing names
    testing_df = pd.read_csv(
        validation_data_file,
        header=0)  # turn the validation set into a testing set

    # scale numerical data (over their flattened versions for joint scaling)
    rss_scaler = StandardScaler(
    )  # the same scaling will be applied to test data later
    # utm_scaler = StandardScaler()  # ditto

    col_aps = [col for col in training_df.columns if 'WAP' in col]
    num_aps = len(col_aps)
    rss = np.asarray(training_df[col_aps], dtype=np.float32)
    rss = (rss_scaler.fit_transform(rss.reshape((-1, 1)))).reshape(rss.shape)

    # utm_x = np.asarray(training_df['LONGITUDE'], dtype=np.float32)
    # utm_y = np.asarray(training_df['LATITUDE'], dtype=np.float32)
    # utm = utm_scaler.fit_transform(np.column_stack((utm_x, utm_y)))
    # num_coords = utm.shape[1]

    # map reference points to sequential IDs per building & floor before building labels
    training_df['REFPOINT'] = training_df.apply(lambda row: str(int(row['SPACEID'])) + str(int(row['RELATIVEPOSITION'])), axis=1) # add a new column
    blds = np.unique(training_df[['BUILDINGID']])
    flrs = np.unique(training_df[['FLOOR']])
    # x_avg = {}
    # y_avg = {}
    for bld in blds:
        for flr in flrs:
            # map reference points to sequential IDs per building-floor before building labels
            cond = (training_df['BUILDINGID'] == bld) & (
                training_df['FLOOR'] == flr)
            _, idx = np.unique(
                training_df.loc[cond, 'REFPOINT'],
                return_inverse=True)  # refer to numpy.unique manual
            training_df.loc[cond, 'REFPOINT'] = idx

            # # calculate the average coordinates of each building/floor
            # x_avg[str(bld) + '-' + str(flr)] = np.mean(
            #     training_df.loc[cond, 'LONGITUDE'])
            # y_avg[str(bld) + '-' + str(flr)] = np.mean(
            #     training_df.loc[cond, 'LATITUDE'])

    # build labels for the multi-class classification of a building, a floor, and a reference point
    num_training_samples = len(training_df)
    num_testing_samples = len(testing_df)
    blds = training_df['BUILDINGID'].map(str)
    flrs = training_df['FLOOR'].map(str)
    rfps = training_df['REFPOINT'].map(str)
    tv_labels = np.asarray(pd.get_dummies(
        blds + '-' + flrs + '-' + rfps))  # labels for training/validation
    # labels is an array of 19937 x 905
    # - 3 for BUILDINGID
    # - 5 for FLOOR,
    # - 110 for REFPOINT
    output_dim = tv_labels.shape[1]

    # create a model
    model = KerasClassifier(
        build_fn=siso_classification,
        input_dim=num_aps,
        output_dim=output_dim,
        hidden_layers=hidden_layers,
        optimizer='adam',
        dropout=dropout,
        epochs=epochs,
        batch_size=batch_size,
        verbose=verbose)

    # define the grid search parameters
    optimizer = [
        'sgd', 'rmsprop', 'adagrad', 'adadelta', 'adam', 'adamax', 'nadam'
    ]
    # dropout = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
    # epochs = [50, 100]
    # param_grid = dict(batch_size=dropout, epochs=epochs)
    param_grid = dict(optimizer=optimizer)

    # train and evaluate the model with k-fold cross validation
    startTime = timer()
    if gpu_id >= 0:  # using GPU
        n_jobs = 1
    else:  # using CPU
        n_jobs = -1
    grid = GridSearchCV(estimator=model, param_grid=param_grid, n_jobs=n_jobs)
    grid_result = grid.fit(rss, tv_labels)
    elapsedTime = timer() - startTime
    print("Model trained in %e s." % elapsedTime)
    print("Best: %f using %s" % (grid_result.best_score_,
                                 grid_result.best_params_))
    means = grid_result.cv_results_['mean_test_score']
    stds = grid_result.cv_results_['std_test_score']
    params = grid_result.cv_results_['params']
    for mean, stdev, param in zip(means, stds, params):
        print("%f (%f) with: %r" % (mean, stdev, param))

    # # turn the given validation set into a testing set
    # # testing_df = pd.read_csv(validation_data_file, header=0)
    # test_AP_features = scale(np.asarray(testing_df.iloc[:,0:520]).astype(float), axis=1) # convert integer to float and scale jointly (axis=1)
    # x_test_utm = np.asarray(testing_df['LONGITUDE'])
    # y_test_utm = np.asarray(testing_df['LATITUDE'])
    # # blds = np.asarray(pd.get_dummies(testing_df['BUILDINGID']))
    # blds = blds_all[len_train:]
    # # flrs = np.asarray(pd.get_dummies(testing_df['FLOOR']))
    # flrs = flrs_all[len_train:]

    # ### evaluate the model
    # print("\nPart 3: evaluating the model ...")

    # # calculate the accuracy of building and floor estimation
    # preds = model.predict(test_AP_features, batch_size=batch_size)
    # n_preds = preds.shape[0]
    # # blds_results = (np.equal(np.argmax(test_labels[:, :3], axis=1), np.argmax(preds[:, :3], axis=1))).astype(int)
    # blds_results = (np.equal(np.argmax(blds, axis=1), np.argmax(preds[:, :3], axis=1))).astype(int)
    # acc_bld = blds_results.mean()
    # # flrs_results = (np.equal(np.argmax(test_labels[:, 3:8], axis=1), np.argmax(preds[:, 3:8], axis=1))).astype(int)
    # flrs_results = (np.equal(np.argmax(flrs, axis=1), np.argmax(preds[:, 3:8], axis=1))).astype(int)
    # acc_flr = flrs_results.mean()
    # acc_bf = (blds_results*flrs_results).mean()
    # # rfps_results = (np.equal(np.argmax(test_labels[:, 8:118], axis=1), np.argmax(preds[:, 8:118], axis=1))).astype(int)
    # # acc_rfp = rfps_results.mean()
    # # acc = (blds_results*flrs_results*rfps_results).mean()

    # # calculate positioning error when building and floor are correctly estimated
    # mask = np.logical_and(blds_results, flrs_results) # mask index array for correct location of building and floor
    # x_test_utm = x_test_utm[mask]
    # y_test_utm = y_test_utm[mask]
    # blds = blds[mask]
    # flrs = flrs[mask]
    # rfps = (preds[mask])[:, 8:118]

    # n_success = len(blds)       # number of correct building and floor location
    # # blds = np.greater_equal(blds, np.tile(np.amax(blds, axis=1).reshape(n_success, 1), (1, 3))).astype(int) # set maximum column to 1 and others to 0 (row-wise)
    # # flrs = np.greater_equal(flrs, np.tile(np.amax(flrs, axis=1).reshape(n_success, 1), (1, 5))).astype(int) # ditto

    # n_loc_failure = 0
    # sum_pos_err = 0.0
    # sum_pos_err_weighted = 0.0
    # idxs = np.argpartition(rfps, -N)[:, -N:]  # (unsorted) indexes of up to N nearest neighbors
    # threshold = scaling*np.amax(rfps, axis=1)
    # for i in range(n_success):
    #     xs = []
    #     ys = []
    #     ws = []
    #     for j in idxs[i]:
    #         rfp = np.zeros(110)
    #         rfp[j] = 1
    #         rows = np.where((train_labels == np.concatenate((blds[i], flrs[i], rfp))).all(axis=1)) # tuple of row indexes
    #         if rows[0].size > 0:
    #             if rfps[i][j] >= threshold[i]:
    #                 xs.append(training_df.loc[training_df.index[rows[0][0]], 'LONGITUDE'])
    #                 ys.append(training_df.loc[training_df.index[rows[0][0]], 'LATITUDE'])
    #                 ws.append(rfps[i][j])
    #     if len(xs) > 0:
    #         sum_pos_err += math.sqrt((np.mean(xs)-x_test_utm[i])**2 + (np.mean(ys)-y_test_utm[i])**2)
    #         sum_pos_err_weighted += math.sqrt((np.average(xs, weights=ws)-x_test_utm[i])**2 + (np.average(ys, weights=ws)-y_test_utm[i])**2)
    #     else:
    #         n_loc_failure += 1
    #         key = str(np.argmax(blds[i])) + '-' + str(np.argmax(flrs[i]))
    #         pos_err = math.sqrt((x_avg[key]-x_test_utm[i])**2 + (y_avg[key]-y_test_utm[i])**2)
    #         sum_pos_err += pos_err
    #         sum_pos_err_weighted += pos_err
    # # mean_pos_err = sum_pos_err / (n_success - n_loc_failure)
    # mean_pos_err = sum_pos_err / n_success
    # # mean_pos_err_weighted = sum_pos_err_weighted / (n_success - n_loc_failure)
    # mean_pos_err_weighted = sum_pos_err_weighted / n_success
    # loc_failure = n_loc_failure / n_success # rate of location estimation failure given that building and floor are correctly located

    ### print out final results
    base_dir = '../results/tune/' + (os.path.splitext(
        os.path.basename(__file__))[0]).replace('tune_', '')
    pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)
    base_file_name = base_dir + "/E{0:d}_B{1:d}_D{2:.2f}_H{3:s}".format(
        epochs, batch_size, dropout, args.hidden_layers.replace(',', '-'))
    # + '_T' + "{0:.2f}".format(args.training_ratio) \
    # sae_model_file = base_file_name + '.hdf5'
    now = datetime.datetime.now()
    output_file_base = base_file_name + '_' + now.strftime("%Y%m%d-%H%M%S")

    with open(output_file_base + '.org', 'w') as output_file:
        output_file.write(
            "#+STARTUP: showall\n")  # unfold everything when opening
        output_file.write("* System parameters\n")
        output_file.write("  - Optimizer: %s\n" % optimizer)
        output_file.write("  - Random number seed: %d\n" % random_seed)
        # output_file.write("  - Ratio of training data to overall data: %.2f\n" % training_ratio)
        output_file.write("  - Epochs: %d\n" % epochs)
        output_file.write("  - Batch size: %d\n" % batch_size)
        output_file.write("  - Dropout rate: %.2f\n" % dropout)
        output_file.write("  - Hidden layers: %d" % hidden_layers[0])
        for units in hidden_layers[1:]:
            output_file.write("-%d" % units)
        output_file.write("\n")
        output_file.write("* Performance\n")
        for mean, stdev, param in zip(means, stds, params):
            output_file.write("%f (%f) with: %r" % (mean, stdev, param))
        # output_file.write("  - Loss (overall): %e\n" % results.losses.overall)
        # output_file.write("  - Accuracy (overall): %e\n" % results.accuracy.overall)
        # output_file.write("  - Building hit rate [%%]: %.2f\n" % (100*results.metrics.building_acc))
        # output_file.write("  - Floor hit rate [%%]: %.2f\n" % (100*results.metrics.floor_acc))
        # output_file.write("  - Building-floor hit rate [%%]: %.2f\n" % (100*results.metrics.bf_acc))
        # output_file.write("  - MSE (location): %e\n" % results.metrics.location_mse)
        # output_file.write("  - Mean error [m]: %.2f\n" % results.metrics.mean_error)  # according to EvAAL/IPIN 2015 competition rule
        # output_file.write("  - Median error [m]: %.2f\n" % results.metrics.median_error)  # ditto
