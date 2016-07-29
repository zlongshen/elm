import copy
import contextlib
import datetime
import os
import tempfile

import pytest
import yaml

from elm.pipeline import pipeline
from elm.config import DEFAULTS, DEFAULTS_FILE, import_callable
from elm.model_selection import ALL_MODELS_DICT
from elm.model_selection import get_args_kwargs_defaults
from elm.pipeline.tests.util import (tmp_dirs_context,
                                     test_one_config as tst_one_config,
                                     remove_pipeline_transforms)
from elm.model_selection.sklearn_support import ALL_MODELS_ESTIMATOR_TYPES
config = copy.deepcopy(DEFAULTS)
for step in config['pipeline']:
    if 'train' in step:
        DEFAULT_TRAIN_KEY = step['train']
        DEFAULT_TRAIN = config['train'][step['train']]
    if 'predict' in step:
        DEFAULT_PREDICT_KEY = step['predict']
        DEFAULT_PREDICT = config['train'][step['predict']]

def test_default_config():
    tag = 'run-with-default-config'
    with tmp_dirs_context(tag) as (train_path, predict_path, cwd):
        out = tst_one_config(config=DEFAULTS, cwd=cwd)
        len_train, len_predict = map(os.listdir, (train_path, predict_path))
        assert len_train
        assert len_predict

@contextlib.contextmanager
def new_training_config(**train_kwargs):
    config = copy.deepcopy(DEFAULTS)
    config['train'][DEFAULT_TRAIN_KEY].update(train_kwargs)
    try:
        yield config
    finally:
        config['train'][DEFAULT_TRAIN_KEY] = DEFAULT_TRAIN

def adjust_config_sample_size(config, n_rows):
    '''Add a step to "sample_pipeline" for limiting
    the number of rows to a random subset of n_rows'''
    for step in config['pipeline']:
        if 'train' in step or 'predict' in step:
            random_rows = [{'random_sample': n_rows}]
            if 'sample_pipeline' in step:
                step['sample_pipeline'] += random_rows
            else:
                step['sample_pipeline'] = random_rows

# The following slow_models take longer than about 11 seconds
# to fit / predict a sample of size (500, 11) with default init kwargs
slow_models = ('ARDRegression',
               'TheilSenRegressor',
               'GaussianProcess',
               'Birch',
               'LogisticRegressionCV')
# The MultiTask* models are not handled yet
multi_task = ('MultiTaskLasso',
              'MultiTaskElasticNetCV',
              'MultiTaskElasticNet',
              'MultiTaskLassoCV')

def get_type(model_init_class):
    return ALL_MODELS_ESTIMATOR_TYPES[model_init_class]


def tst_sklearn_method(model_init_class, c, n_rows, use_transform=True):
    '''This func can test almost all sklearn clusterers, regressors,
    or classifiers as they are used in the config / pipeline system

    Params:
        model_init_class: model class as string, e.g.
            'sklearn.linear_model:SGDRegressor'
        c:  the class as imported
        n_rows:  controls the # of rows in sample size (None= all rows)
                 int means take random sample
        use_transform: True - leave transforms in pipeline / sample_pipeline
                       False - no transforms before ML models
    Tests the following:
        * Each model in sklearn can be passed through the config train/predict cycle
        * Pickles and netcdfs show up if prediction is used
        * partial_fit, fit or transform can be called if given
        * Each model in sklearn can take a transform step in pipeline
        * Each model can get a scoring that depends on supervised/unsupervised
        * Model selection logic works for ensembles
    '''
    tag = '{}-n_rows-{}'.format(model_init_class, n_rows)
    if 'DictionaryLearning' in model_init_class:
        pytest.skip('Too slow (DictionaryLearning on random data)')
    if 'SpectralCluster' in model_init_class:
        pytest.skip('SpectralClustering with random data has little connectivity')

    with tmp_dirs_context(tag) as (train_path, predict_path, cwd):
        # make a small ensemble for simplicity
        default_ensemble =  {
                              'init_ensemble_size': 2,  # how many models to initialize at start
                              'saved_ensemble_size': 1, # how many models to serialize as "best"
                              'n_generations': 1,       # how many model train/select generations
                              'batches_per_gen': 1,     # how many partial_fit calls per train/select generation
                            }
        default_init_kwargs = copy.deepcopy(DEFAULT_TRAIN['model_init_kwargs'])
        # Initialize the model given in arguments
        kwargs = {'model_init_class': model_init_class,
                  'model_selection': 'no_selection',
                  'ensemble_kwargs': default_ensemble,
                  'model_init_kwargs': default_init_kwargs}
        if not hasattr(c, 'predict'):
            # TODO: handle models with "fit_transform"
            # or "transform" methods (ones without a "predict")
            has_predict = False
        else:
            has_predict = True
        if any(m in model_init_class for m in multi_task):
            pytest.xfail('{} models from sklearn are unsupported'.format(model_init_class))
        method_args, method_kwargs, _ = get_args_kwargs_defaults(c.fit)
        kwargs['model_init_kwargs'] = {}
        kwargs['model_scoring'] = None
        DEFAULT_DS_KEY = DEFAULTS['train'][DEFAULT_TRAIN_KEY]['data_source']
        data_sources = DEFAULTS['data_sources']
        data_source = data_sources[DEFAULT_DS_KEY]
        if any(a.lower() == 'y' for a in method_args):
            #  supervised
            model_type = get_type(model_init_class)
            if model_type == 'classifier' or 'LogisticRegression' in model_init_class:
                data_source['get_y_func'] = 'elm.pipeline.tests.util:example_get_y_func_binary'
                kwargs['model_scoring'] = 'accuracy_score_cv'
                kwargs['model_selection'] = 'select_top_n'
                kwargs['model_selection_kwargs'] = {'top_n': 1}
                if 'LogisticRegression' in model_init_class:
                    kwargs['model_scoring'] = kwargs['model_selection'] = None
            else:
                data_source['get_y_func'] = 'elm.pipeline.tests.util:example_get_y_func_continuous'
                kwargs['model_scoring'] = None
                kwargs['model_selection'] = None
        if 'MiniBatchKMeans' in model_init_class:
            kwargs['model_scoring'] = "ensemble_kmeans_scoring"
            kwargs['model_selection'] = "kmeans_model_averaging"
        if 'OrthogonalMatchingPursuit' in model_init_class:
            # This is incorrectly classified as a continuous
            # model in the if block a few lines above
            kwargs['model_scoring'] = None
            kwargs['model_selection'] = None
        if model_init_class.endswith('CV'):
            kwargs['model_scoring'] = None
            kwargs['model_selection'] = None
        if any(s in model_init_class for s in slow_models):
            # These are too slow for most image classification
            # uses
            pytest.skip('{} is too slow for this test'.format(model_init_class))
        methods = set(dir(c))
        if 'partial_fit' in methods:
            kwargs['fit_method'] = 'partial_fit'
        else:
            kwargs['fit_method'] = 'fit'
        with new_training_config(**kwargs) as config:
            if not use_transform:
                remove_pipeline_transforms(config)
            if n_rows:
                adjust_config_sample_size(config, n_rows)
            for item in config['pipeline']:
                if item.get('method'):
                    item['method'] = kwargs['fit_method']
                if item.get('method') != 'partial_fit':
                    item.pop('batch_size', 0)
                if not use_transform:
                    item['sample_pipeline'] = [item2 for item2 in item.get('sample_pipeline', [])
                                               if not 'transform' in item2]
            if not has_predict:
                config['pipeline'] = [_ for _ in config['pipeline'] if not 'predict' in _]
            config['data_sources'][DEFAULT_DS_KEY] = data_source
            with open('tested_config_{}.yaml'.format(model_init_class.split(':')[-1]), 'w') as f:
                f.write(yaml.dump(config))
            log = tst_one_config(config=config, cwd=cwd)
            train_outputs_tmp = os.path.join(train_path, DEFAULT_TRAIN_KEY)
            assert os.path.exists(train_outputs_tmp)
            train_outputs = os.listdir(train_outputs_tmp)
            assert train_outputs
            pickles = [t for t in train_outputs if t.endswith('.pkl')]
            assert pickles
            if has_predict:
                predict_path_tmp = os.path.join(predict_path, DEFAULT_TRAIN_KEY)
                assert os.path.exists(predict_path_tmp)
                predict_outputs = os.listdir(predict_path_tmp)
                assert predict_outputs
                netcdfs, xarrays = [[p for p in predict_outputs if p.endswith(end)]
                        for end in ('.nc', '.xr')]
                assert netcdfs
                assert xarrays


@pytest.mark.slow
@pytest.mark.parametrize('model_init_class,func', sorted(ALL_MODELS_DICT.items()))
def test_sklearn_methods_slow(model_init_class, func):
    '''Test running each classifier/regressor/cluster model
    through the default pipeline adjusted as necessary, where
    the training sample size is a full file (None as n_rows)

    pytest.mark.parametrize calls this
    function once for each model_init_class in ALL_MODELS_DICT

    Does not use PCA transforms
    '''
    tst_sklearn_method(model_init_class, func, None, use_transform=False)


@pytest.mark.slow
@pytest.mark.parametrize('model_init_class,func', sorted(ALL_MODELS_DICT.items()))
def test_sklearn_methods_transform(model_init_class, func):
    '''Test running each classifier/regressor/cluster model
    through the default pipeline adjusted as necessary, where
    the training sample size is random small
    subset of one file's rows

    pytest.mark.parametrize calls this
    function once for each model_init_class in ALL_MODELS_DICT

    Uses PCA transform before each model
    '''
    tst_sklearn_method(model_init_class, func, None, use_transform=True)


@pytest.mark.parametrize('model_init_class,func', sorted(ALL_MODELS_DICT.items()))
def test_sklearn_methods_fast(model_init_class, func):
    '''Test running each classifier/regressor/cluster model
    through the default pipeline adjusted as necessary, where
    the training sample size is random small
    subset of one file's rows

    pytest.mark.parametrize calls this
    function once for each model_init_class in ALL_MODELS_DICT

    Does not use PCA transform
    '''
    tst_sklearn_method(model_init_class, func, 500, use_transform=False)
