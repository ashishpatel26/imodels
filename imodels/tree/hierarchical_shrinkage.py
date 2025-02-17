from copy import deepcopy
from typing import List

import numpy as np
from sklearn import datasets
from sklearn.base import BaseEstimator
from sklearn.metrics import r2_score
from sklearn.model_selection import cross_val_score
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeRegressor

from imodels.util import checks


class HSTree:
    def __init__(self, estimator_: BaseEstimator, reg_param: float = 1, shrinkage_scheme_: str = 'node_based'):
        """HSTree (Tree with hierarchical shrinkage applied).
        Hierarchical shinkage is an extremely fast post-hoc regularization method which works on any decision tree (or tree-based ensemble, such as Random Forest).
        It does not modify the tree structure, and instead regularizes the tree by shrinking the prediction over each node towards the sample means of its ancestors (using a single regularization parameter).
        Experiments over a wide variety of datasets show that hierarchical shrinkage substantially increases the predictive performance of individual decision trees and decision-tree ensembles.
        https://arxiv.org/abs/2202.00858

        Params
        ------
        estimator_: sklearn tree or tree ensemble model (e.g. RandomForest or GradientBoosting)

        reg_param: float
            Higher is more regularization (can be arbitrarily large, should not be < 0)
        
        shrinkage_scheme: str
            Experimental: Used to experiment with different forms of shrinkage. options are: 
                (i) node_based shrinks based on number of samples in parent node
                (ii) leaf_based only shrinks leaf nodes based on number of leaf samples 
                (iii) constant shrinks every node by a constant lambda
        """
        super().__init__()
        self.reg_param = reg_param
        # print('est', estimator_)
        self.estimator_ = estimator_
        self.shrinkage_scheme_ = shrinkage_scheme_
        self._init_prediction_task()

        if checks.check_is_fitted(self.estimator_):
            self.shrink()

    def __init__prediction_task(self):
        self.prediction_task = 'regression'

    def get_params(self, deep=True):
        if deep:
            return deepcopy({'reg_param': self.reg_param, 'estimator_': self.estimator_,
                             # 'prediction_task': self.prediction_task,
                             'shrinkage_scheme_': self.shrinkage_scheme_})
        return {'reg_param': self.reg_param, 'estimator_': self.estimator_,
                # 'prediction_task': self.prediction_task,
                'shrinkage_scheme_': self.shrinkage_scheme_}

    def fit(self, *args, **kwargs):
        self.estimator_.fit(*args, **kwargs)
        self.shrink()

    def shrink_tree(self, tree, reg_param, i=0, parent_val=None, parent_num=None, cum_sum=0):
        """Shrink the tree
        """
        if reg_param is None:
            reg_param = 1.0
        left = tree.children_left[i]
        right = tree.children_right[i]
        is_leaf = left == right
        n_samples = tree.n_node_samples[i]
        if self.prediction_task == 'regression':
            val = tree.value[i][0, 0]
        else:
            if len(tree.value[i][0]) == 1:
                val = tree.value[i][0, 0]
            else:
                val = tree.value[i][0, 1] / (tree.value[i][0, 0] + tree.value[i][0, 1])  # binary classification

        # if root
        if parent_val is None and parent_num is None:
            if not is_leaf:
                self.shrink_tree(tree, reg_param, left,
                                 parent_val=val, parent_num=n_samples, cum_sum=val)
                self.shrink_tree(tree, reg_param, right,
                                 parent_val=val, parent_num=n_samples, cum_sum=val)

        # if has parent
        else:
            if self.shrinkage_scheme_ == 'node_based':
                val_new = (val - parent_val) / (1 + reg_param / parent_num)
            elif self.shrinkage_scheme_ == 'constant':
                val_new = (val - parent_val) / (1 + reg_param)
            else:
                val_new = val
            cum_sum += val_new
            if is_leaf:
                if self.prediction_task == 'regression':
                    if self.shrinkage_scheme_ == 'node_based' or self.shrinkage_scheme_ == 'constant':
                        tree.value[i, 0, 0] = cum_sum
                    else:
                        # tree.value[i, 0, 0] = cum_sum/(1 + reg_param/n_samples)
                        tree.value[i, 0, 0] = tree.value[0][0, 0] + (val - tree.value[0][0, 0]) / (
                                1 + reg_param / n_samples)
                else:
                    if len(tree.value[i][0]) == 1:
                        if self.shrinkage_scheme_ == 'node_based' or self.shrinkage_scheme_ == 'constant':
                            tree.value[i, 0, 0,] = cum_sum
                        else:
                            tree.value[i, 0, 0,] = tree.value[0][0, 0] + (val - tree.value[0][0, 0]) / (
                                    1 + reg_param / n_samples)
                    else:
                        if self.shrinkage_scheme_ == 'node_based' or self.shrinkage_scheme_ == 'constant':
                            tree.value[i, 0, 1] = cum_sum
                            tree.value[i, 0, 0] = 1.0 - cum_sum
                        else:
                            root_prediction = tree.value[0][0, 1] / (tree.value[0][0, 0] + tree.value[0][0, 1])
                            tree.value[i, 0, 1] = root_prediction + (val - root_prediction) / (
                                    1 + reg_param / n_samples)
                            tree.value[i, 0, 0] = 1.0 - tree.value[i, 0, 1]
            else:
                if self.prediction_task == 'regression':
                    tree.value[i][0, 0] = parent_val + val_new
                else:
                    if len(tree.value[i][0]) == 1:
                        tree.value[i][0, 0] = parent_val + val_new
                    else:
                        tree.value[i][0, 1] = parent_val + val_new
                        tree.value[i][0, 0] = 1.0 - parent_val + val_new

                self.shrink_tree(tree, reg_param, left,
                                 parent_val=val, parent_num=n_samples, cum_sum=cum_sum)
                self.shrink_tree(tree, reg_param, right,
                                 parent_val=val, parent_num=n_samples, cum_sum=cum_sum)

                # edit the non-leaf nodes for later visualization (doesn't effect predictions)

                # pass  # not sure exactly what to put here

        return tree

    def shrink(self):
        if hasattr(self.estimator_, 'tree_'):
            self.shrink_tree(self.estimator_.tree_, self.reg_param)
        elif hasattr(self.estimator_, 'estimators_'):
            for t in self.estimator_.estimators_:
                if isinstance(t, np.ndarray):
                    assert t.size == 1, 'multiple trees stored under tree_?'
                    t = t[0]
                self.shrink_tree(t.tree_, self.reg_param)

    def predict(self, *args, **kwargs):
        return self.estimator_.predict(*args, **kwargs)

    def predict_proba(self, *args, **kwargs):
        if hasattr(self.estimator_, 'predict_proba'):
            return self.estimator_.predict_proba(*args, **kwargs)
        else:
            return NotImplemented

    def score(self, *args, **kwargs):
        if hasattr(self.estimator_, 'score'):
            return self.estimator_.score(*args, **kwargs)
        else:
            return NotImplemented


class HSTreeRegressor(HSTree):
    def _init_prediction_task(self):
        self.prediction_task = 'regression'


class HSTreeClassifier(HSTree):
    def _init_prediction_task(self):
        self.prediction_task = 'classification'


class HSTreeClassifierCV(HSTreeClassifier):
    def __init__(self, estimator_: BaseEstimator,
                 reg_param_list: List[float] = [0.1, 1, 10, 50, 100, 500], shrinkage_scheme_: str = 'node_based',
                 cv: int = 3, scoring=None, *args, **kwargs):
        """Note: args, kwargs are not used but left so that imodels-experiments can still pass redundant args.
        Cross-validation is used to select the best regularization parameter for hierarchical shrinkage.
        """
        super().__init__(estimator_, reg_param=None)
        self.reg_param_list = np.array(reg_param_list)
        self.cv = cv
        self.scoring = scoring
        self.shrinkage_scheme_ = shrinkage_scheme_
        # print('estimator', self.estimator_,
        #       'checks.check_is_fitted(estimator)', checks.check_is_fitted(self.estimator_))
        # if checks.check_is_fitted(self.estimator_):
        #     raise Warning('Passed an already fitted estimator,'
        #                   'but shrinking not applied until fit method is called.')

    def fit(self, X, y, *args, **kwargs):
        self.scores_ = []
        for reg_param in self.reg_param_list:
            est = HSTreeClassifier(deepcopy(self.estimator_), reg_param)
            cv_scores = cross_val_score(est, X, y, cv=self.cv, scoring=self.scoring)
            self.scores_.append(np.mean(cv_scores))
        self.reg_param = self.reg_param_list[np.argmax(self.scores_)]
        super().fit(X=X, y=y)


class HSTreeRegressorCV(HSTreeRegressor):
    def __init__(self, estimator_: BaseEstimator,
                 reg_param_list: List[float] = [0.1, 1, 10, 50, 100, 500],
                 shrinkage_scheme_: str = 'node_based',
                 cv: int = 3, scoring=None, *args, **kwargs):
        """Note: args, kwargs are not used but left so that imodels-experiments can still pass redundant args.
        Cross-validation is used to select the best regularization parameter for hierarchical shrinkage.
        """
        super().__init__(estimator_, reg_param=None)
        self.reg_param_list = np.array(reg_param_list)
        self.cv = cv
        self.scoring = scoring
        self.shrinkage_scheme_ = shrinkage_scheme_
        # print('estimator', self.estimator_,
        #       'checks.check_is_fitted(estimator)', checks.check_is_fitted(self.estimator_))
        # if checks.check_is_fitted(self.estimator_):
        #     raise Warning('Passed an already fitted estimator,'
        #                   'but shrinking not applied until fit method is called.')

    def fit(self, X, y):
        self.scores_ = []
        for reg_param in self.reg_param_list:
            est = HSTreeRegressor(deepcopy(self.estimator_), reg_param)
            cv_scores = cross_val_score(est, X, y, cv=self.cv, scoring=self.scoring)
            self.scores_.append(np.mean(cv_scores))
        self.reg_param = self.reg_param_list[np.argmax(self.scores_)]
        super().fit(X=X, y=y)


if __name__ == '__main__':
    np.random.seed(15)
    # X, y = datasets.fetch_california_housing(return_X_y=True)  # regression
    # X, y = datasets.load_breast_cancer(return_X_y=True)  # binary classification
    X, y = datasets.load_diabetes(return_X_y=True)  # regression
    # X = np.random.randn(500, 10)
    # y = (X[:, 0] > 0).astype(float) + (X[:, 1] > 1).astype(float)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.33, random_state=10
    )
    print('X.shape', X.shape)
    print('ys', np.unique(y_train))

    # m = HSTree(estimator_=DecisionTreeClassifier(), reg_param=0.1)
    # m = DecisionTreeClassifier(max_leaf_nodes = 20,random_state=1, max_features=None)
    m = DecisionTreeRegressor(random_state=42, max_leaf_nodes=20)
    # print('best alpha', m.reg_param)
    m.fit(X_train, y_train)
    # m.predict_proba(X_train)  # just run this
    print('score', r2_score(y_test, m.predict(X_test)))
    print('running again....')

    # x = DecisionTreeRegressor(random_state = 42, ccp_alpha = 0.3)
    # x.fit(X_train,y_train)

    # m = HSTree(estimator_=DecisionTreeRegressor(random_state=42, max_features=None), reg_param=10)
    # m = HSTree(estimator_=DecisionTreeClassifier(random_state=42, max_features=None), reg_param=0)
    m = HSTreeClassifierCV(estimator_=DecisionTreeRegressor(max_leaf_nodes=10, random_state=1),
                           shrinkage_scheme_='node_based',
                           reg_param_list=[0.1, 1, 2, 5, 10, 25, 50, 100, 500])
    # m = ShrunkTreeCV(estimator_=DecisionTreeClassifier())

    # m = HSTreeClassifier(estimator_ = GradientBoostingClassifier(random_state = 10),reg_param = 5)
    m.fit(X_train, y_train)
    print('best alpha', m.reg_param)
    # m.predict_proba(X_train)  # just run this
    # print('score', m.score(X_test, y_test))
    print('score', r2_score(y_test, m.predict(X_test)))
