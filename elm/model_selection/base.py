'''
----------------------------

``elm.model_selection.base``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calls given model_selection after sort_fitness is called (if given)

Params:
    :models: sequence of 2-tuples (model_name, model)
    :model_selection: called with the signature:

        * `model_selection(models, best_idxes, **model_selection_kwargs)` /
            where best_idxes is the sorted fitness order if sort_fitness is given /
        * Otherwise if sort_fitness is not given, the signature is: /
            `model_selection(models, **model_selection_kwargs)`

    :sort_fitness: a function, pareto_front by default, to sort scores
            signature: sort_fitness(weights, objectives, take=None)
    :score_weights: passed to sort_fitness as weights, e.g.: /
        [-1, 1] for minimizing the first element of model _score array /
        and maximizing the second element
    :model_selection_kwargs: passed to model_selection

Returns:
    :models: sequence of 2-tuples (model_name, model)
'''

from collections import namedtuple
import copy
from functools import partial
import logging
import inspect

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from elm.config import import_callable

from elm.model_selection.sorting import pareto_front

logger = logging.getLogger(__name__)


def base_selection(models,
                   model_selection=None,
                   sort_fitness=pareto_front,
                   score_weights=None,
                   **model_selection_kwargs):
    '''Calls given model_selection after sort_fitness is called (if given)

    Params:
        :models: sequence of 2-tuples (model_name, model)
        :model_selection: called with the signature:

            * `model_selection(models, best_idxes, **model_selection_kwargs)` /
                where best_idxes is the sorted fitness order if sort_fitness is given /
            * Otherwise if sort_fitness is not given, the signature is: /
                `model_selection(models, **model_selection_kwargs)`

        :sort_fitness: a function, pareto_front by default, to sort scores
                signature: sort_fitness(weights, objectives, take=None)
        :score_weights: passed to sort_fitness as weights, e.g.: /
            [-1, 1] for minimizing the first element of model _score array /
            and maximizing the second element
        :model_selection_kwargs: passed to model_selection

    Returns:
        :models: sequence of 2-tuples (model_name, model)
    '''
    logger.debug('base_selection with kwargs: {}'.format(model_selection_kwargs))
    if sort_fitness == 'pareto_front':
        sort_fitness = pareto_front
    if not model_selection:
        return models
    model_selection_kwargs = model_selection_kwargs or {}
    if score_weights is not None:
        if score_weights is None or not hasattr(score_weights, '__len__'):
            raise ValueError('Expected score_weights keyword arg (array of '
                            '-1 for minmize, 1 for maximize for each scoring matrix column)')
        # scoring has signature: scoring(y, y_pred, **kwargs).
        scores = [model._score for name, model in models]
        scores = np.atleast_2d(np.array(scores))
        if scores.shape[1] == len(models) and scores.shape[0] != len(models):
            scores = scores.T
        if scores.shape[0] != len(models) or len(scores.shape) != 2:
            raise ValueError('Expected scorer to return a scalar or 1-d array. '
                             'Found shape: {}'.format(scores.shape))
        if scores.shape[1] != len(score_weights):
            raise ValueError('Length of score_weights {} does '
                             'not match scores.shape[1] {}'.format(scores.shape[1], len(score_weights)))
        best_idxes = sort_fitness(score_weights, scores)
        models = model_selection(models, best_idxes, **model_selection_kwargs)
    else:
        models = model_selection(models, **model_selection_kwargs)
    return models
