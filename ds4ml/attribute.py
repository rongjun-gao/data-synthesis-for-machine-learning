"""
Attribute: data structure for 1-dimensional cross-sectional data

This class only handle integer, float, string, datetime columns, and it can be
labeled as categorical column.
"""

import numpy as np

from bisect import bisect_right
from random import uniform
from pandas import Series, DataFrame
from dateutil.parser import parse
from datetime import datetime, timedelta

from ds4ml import utils


# Default environment variables for data processing and analysis
DEFAULT_BIN_SIZE = 20


class AttributePattern(object):
    """
    A helper class of ``Attribute`` to store its patterns.
    """
    # _type: date type for handle different kinds of attributes in data
    # synthesis, only support: integer, float, string, datetime.
    _type = None
    categorical = False
    _min = None
    _max = None
    _decimals = None

    # probability distribution (pr)
    bins = None
    prs = None
    _pattern_generated = False

    # Here _bin_size is int-typed (to show the size of histogram bins), which
    # is different from bins in np.histogram.
    _bin_size = DEFAULT_BIN_SIZE


class Attribute(AttributePattern, Series):

    _epoch = datetime(1970, 1, 1)  # for datetime handling

    def __init__(self, *args, **kwargs):
        """
        An improved Series with extra pattern information, e.g. categorical,
        min/max value, and probability distribution.

        The ``Attribute`` class has two modes:

        - it has raw data, and then can calculate its pattern from the data;

        - it doesn't have raw data, and only have the pattern from customer.

        Parameters
        ----------
        categorical : bool
            set categorical label for attribute. If categorical, this attribute
            takes on a limited and fixed number of possible values. Examples:
            blood type, gender.
        """
        categorical = kwargs.pop('categorical', False)
        super().__init__(*args, **kwargs)
        self.set_pattern(categorical=categorical)

    def _calculate_pattern(self):
        from pandas.api.types import infer_dtype
        self._type = infer_dtype(self, skipna=True)
        if self._type == 'integer':
            pass
        elif self._type == 'floating' or self._type == 'mixed-integer-float':
            self._type = 'float'
        elif self._type in ['string', 'mixed-integer', 'mixed']:
            self._type = 'string'
            if all(map(utils.is_datetime, self._values)):
                self._type = 'datetime'

        # fill the missing values with the most frequent value
        self.fillna(self.mode()[0], inplace=True)

        # special handling for datetime attribute
        if self._type == 'datetime':
            self.update(self.map(self._to_seconds).map(self._date_formatter))

        if self._type == 'float':
            self._decimals = self.decimals()

        # The `categorical` option can be set to true when the attribute is
        # string-typed and all values are not unique, and its value can be
        # overrode by user.
        self.categorical = self.categorical or (
                self._type == 'string' and not self.is_unique)
        self._set_domain()
        self._set_distribution()

    # handling functions for datetime attribute
    def _to_seconds(self, timestr):
        return int((parse(timestr) - self._epoch).total_seconds())

    def _date_formatter(self, seconds):
        date = self._epoch + timedelta(seconds=seconds)
        return '%d/%d/%d' % (date.month, date.day, date.year)

    # Take pandas.Series as manipulation result.
    @property
    def _constructor(self):
        return Series

    @property
    def _constructor_expanddim(self):
        from ds4ml.dataset import DataSet
        return DataSet

    def set_pattern(self, pattern=None, **kwargs):
        """
        Set an attribute's pattern, including its type, min/max value, and
        probability distributions.
        If patter is None, then calculation its pattern from its data.
        """
        if not self._pattern_generated:
            self.categorical = kwargs.pop("categorical", False)
            if pattern is None:
                # to calculate the pattern use its data
                self._calculate_pattern()
            else:
                self._type = pattern['type']
                if self.type == 'float':
                    self._decimals = pattern['decimals']
                self.categorical = pattern['categorical']
                self._min = pattern['min']
                self._max = pattern['max']
                self.bins = np.array(pattern['bins'])
                self.prs = np.array(pattern['prs'])
            self._pattern_generated = True

    @property
    def is_numerical(self):
        return self._type == 'integer' or self._type == 'float'

    @property
    def type(self):
        return self._type

    @property
    def domain(self):
        """
        Return attribute's domain, which can be a list of values for categorical
        attribute, and an interval with min/max value for non-categorical
        attribute.
        """
        if self.categorical:
            return self.bins
        else:
            return [self._min, self._max]

    @domain.setter
    def domain(self, domain: list):
        """
        Set attribute's domain, includes min, max, frequency, or distribution.

        Generally, the domain of one attribute can be calculated automatically.
        This method can be manually called for specific purposes, e.g. compare
        two same attributes based on same domain.

        Parameters
        ----------
        domain : list
            domain of one attribute. For numerical or datetime attributes, it
            should be a list of two elements [min, max]; For categorical
            attributes, it should a list of potential values of this attribute.
        """
        # if a attribute is numerical and categorical and domain's length is
        # bigger than 2, take it as categorical. e.g. zip code.
        if self._type == 'datetime':
            domain = list(map(self._to_seconds, domain))
        if (self.is_numerical and self.categorical and len(domain) > 2) or (
                self.categorical):
            self._min, self._max = min(domain), max(domain)
            self.bins = np.array(domain)
        elif self.is_numerical:
            self._min, self._max = domain
            self._step = (self._max - self._min) / self._bin_size
            self.bins = np.array([self._min, self._max])
        elif self._type == 'string':
            lengths = [len(str(i)) for i in domain]
            self._min, self._max = min(lengths), max(lengths)
            self.bins = np.array(domain)
        self._set_distribution()

    def _set_domain(self):
        """
        Compute domain (min, max, distribution bins) from input data
        """
        if self._type == 'string':
            self._items = self.astype(str).map(len)
            self._min = int(self._items.min())
            self._max = int(self._items.max())
            if self.categorical:
                self.bins = self.unique()
            else:
                self.bins = np.array([self._min, self._max])
        elif self._type == 'datetime':
            self.update(self.map(self._to_seconds))
            if self.categorical:
                self.bins = self.unique()
            else:
                self._min = float(self.min())
                self._max = float(self.max())
                self.bins = np.array([self._min, self._max])
                self._step = (self._max - self._min) / self._bin_size
        else:
            self._min = float(self.min())
            self._max = float(self.max())
            if self.categorical:
                self.bins = self.unique()
            else:
                self.bins = np.array([self._min, self._max])
                self._step = (self._max - self._min) / self._bin_size

    def _set_distribution(self):
        if self.categorical:
            counts = self.value_counts()
            for value in set(self.bins) - set(counts.index):
                counts[value] = 0
            counts.sort_index(inplace=True)
            if self.type == 'datetime':
                counts.index = list(map(self._date_formatter, counts.index))
            self._counts = counts.values
            self.prs = utils.normalize_distribution(counts)
            self.bins = np.array(counts.index)
        else:
            # Note: hist, edges = numpy.histogram(), all but the last bin
            # is half-open. If bins is 20, then len(hist)=20, len(edges)=21
            if self.type == 'string':
                hist, edges = np.histogram(self._items,
                                           bins=self._bin_size)
            else:
                hist, edges = np.histogram(self, bins=self._bin_size,
                                           range=(self._min, self._max))
            self.bins = edges[:-1]  # Remove the last bin edge
            self._counts = hist
            self.prs = utils.normalize_distribution(hist)
            if self.type == 'integer':
                self._min = int(self._min)
                self._max = int(self._max)

    def counts(self, bins=None, normalize=True):
        """
        Return an array of counts (or normalized density) of unique values.

        This function works with `attribute.bins`. Combination of both are
        like `Series.value_counts`. The parameter `bins` can be none, or a list.
        """
        if bins is None:
            return self._counts
        if self.categorical:
            if self.type == 'datetime':
                bins = list(map(self._to_seconds, bins))
            counts = self.value_counts()
            for value in set(bins) - set(counts.index):
                counts[value] = 0
            if normalize:
                return np.array([round(counts.get(b)/sum(counts) * 100, 2)
                                 for b in bins])
            else:
                return np.array([counts.get(b) for b in bins])
        else:
            if len(bins) == 1:
                return np.array([self.size])
            hist, _ = np.histogram(self, bins=bins)
            if normalize:
                return (hist / hist.sum() * 100).round(2)
            else:
                return hist

    def bin_indexes(self):
        """
        Encode values into bin indexes for Bayesian Network.
        """
        if self.categorical:
            mapping = {value: idx for idx, value in enumerate(self.bins)}
            indexes = self.map(lambda x: mapping[x], na_action='ignore')
        else:
            indexes = self.map(lambda x: bisect_right(self.bins, x) - 1,
                               na_action='ignore')
        indexes.fillna(len(self.bins), inplace=True)
        return indexes.astype(int, copy=False)

    def to_pattern(self):
        """
        Return attribution's metadata information in JSON format or Python
        dictionary. Usually used in debug and testing.
        """
        return {
            'name': self.name,
            'type': self._type,
            'categorical': self.categorical,
            'min': self._min,
            'max': self._max,
            'decimals': self._decimals if self.type == 'float' else None,
            'bins': self.bins.tolist(),
            'prs': self.prs.tolist()
        }

    def decimals(self):
        """
        Returns number of decimals places for floating attribute. Used for
        generated dataset to keep consistent decimal places for float attribute.
        """
        def decimals_of(value: float):
            value = str(value)
            return len(value) - value.rindex('.') - 1

        vc = self.map(decimals_of).value_counts()
        slot = 0
        for i in range(len(vc)):
            if sum(vc.head(i + 1)) / sum(vc) > 0.8:
                slot = i + 1
                break
        return max(vc.index[:slot])

    def pseudonymize(self, size=None):
        """
        Return pseudonymized values for this attribute, which is used to
        substitute identifiable data with a reversible, consistent value.
        """
        size = size or self.size
        if size != self.size:
            attr = Series(np.random.choice(self.bins, size=size, p=self.prs))
        else:
            attr = self
        if self.categorical:
            mapping = {b: utils.pseudonymise_string(b) for b in self.bins}
            return attr.map(lambda x: mapping[x])

        if self._type == 'string':
            return attr.map(utils.pseudonymise_string)
        elif self.is_numerical or self._type == 'datetime':
            return attr.map(str).map(utils.pseudonymise_string)

    def random(self, size=None):
        """
        Return an random array with same length (usually used for
        non-categorical attribute).
        """
        size = size or self.size
        if self._min == self._max:
            rands = np.ones(size) * self._min
        else:
            rands = np.arange(self._min, self._max,
                              (self._max - self._min) / size)

        np.random.shuffle(rands)
        if self._type == 'string':
            if self._min == self._max:
                length = self._min
            else:
                length = np.random.randint(self._min, self._max)
            vectorized = np.vectorize(lambda x: utils.randomize_string(length))
            rands = vectorized(rands)
        elif self._type == 'integer':
            rands = list(map(int, rands))
        elif self._type == 'datetime':
            rands = list(map(self._date_formatter, rands))
        return Series(rands)

    def _random_sample_at(self, index: int):
        """ Sample a value from distribution bins at position 'index'"""
        if self.categorical:
            return self.bins[index]

        length = len(self.bins)
        if index < length - 1:
            return uniform(self.bins[index], self.bins[index + 1])
        else:
            return uniform(self.bins[-1], self._max)

    def choice(self, size=None, indexes=None):
        """
        Return a random sample based on this attribute's probability and
        distribution bins (default value is base random distribution bins based
        on its probability).

        Parameters
        ----------
        size : int
            size of random sample

        indexes : array-like
            array of indexes in distribution bins
        """
        if indexes is None:
            size = size or self.size
            indexes = Series(np.random.choice(len(self.prs),
                                              size=size, p=self.prs))
        column = indexes.map(lambda x: self._random_sample_at(x))
        if self.type == 'datetime':
            if not self.categorical:
                column = column.map(self._date_formatter)
        elif self.type == 'float':
            column = column.round(self._decimals)
        elif self.type == 'integer':
            column = column.round().astype(int)
        elif self.type == 'string':
            if not self.categorical:
                column = column.map(lambda x: utils.randomize_string(int(x)))
        return column

    def encode(self, data=None):
        """
        Encode labels to normalized encoding.

        Parameters
        ----------
        data : array-like
            target values
        """
        if data is None:
            data = self.copy()
        else:
            if self.type == 'datetime':
                if all(map(utils.is_datetime, data)):
                    data = data.map(self._to_seconds)
                else:
                    data = data.map(int)

        if self.categorical:
            df = DataFrame()
            for c in self.bins:
                df[c] = data.apply(lambda v: 1 if v == c else 0)
            return df

        if self.type != 'string':
            return data.apply(lambda v:  # 1e-8 is a small delta
                              int((v - self._min) / (self._step + 1e-8))
                              / self._bin_size)
        else:
            raise ValueError('Non-categorical attribute does not need encode '
                             'method.')
