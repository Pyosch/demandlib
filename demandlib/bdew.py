# -*- coding: utf-8 -*-
"""
Implementation of the bdew heat load profiles


"""
from math import ceil
import numpy as np
import pandas as pd
import os
from oemof.tools.helpers import create_basic_dataframe as basic_df


class HeatBuilding:
    """
    Parameters
    ----------
    year : int
        year or which the profile is created

    Attributes
    ----------
    datapath : string
        path to the bdew basic data files (csv)
    temperature : pandas.Series
        Series containing hourly temperature data
    annual_heat_demand : float
        annual heat demand of building in kWh
    building_class: int
        class of building according to bdew classification
        possible numbers are: 1 - 11
    shlp_type : string
        type of standardized heat load profile according to bdew
        possible types are:
        GMF, GPD, GHD, GWA, GGB, EFH, GKO, MFH, GBD, GBA, GMK, GBH, GGA, GHA
    wind_class : int
        wind classification for building location (0=not windy or 1=windy)
    ww_incl : boolean
        decider whether warm water load is included in the heat load profile
    """
    def __init__(self, year, **kwargs):
        self.datapath = kwargs.get(
            'datapath', os.path.join(os.path.dirname(__file__), 'bdew_data'))
        self.df = basic_df(year, holidays=kwargs.get('holidays'))
        self.df['weekday'].mask(self.df['weekday'] == 0, 7, True)
        self.temperature = kwargs.get('temperature')
        self.annual_heat_demand = kwargs.get('annual_heat_demand')
        self.shlp_type = kwargs.get('shlp_type')
        self.wind_class = kwargs.get('wind_class')
        self.building_class = kwargs.get('building_class', 0)
        self.ww_incl = kwargs.get('ww_incl', True)
        self.name = kwargs.get('name', self.shlp_type)

    def weighted_temperature(self, how="geometric_series"):
        r"""
            A new temperature vector is generated containing a multi-day
            average temperature as needed in the load profile function.

            Parameters
            ----------
            how : string
                string which type to return ("geometric_series" or "mean")

            Notes
            -----
            Equation for the mathematical series of the average
            tempaerature [1]_:

            .. math::
                T=\frac{T_{D}+0.5\cdot T_{D-1}+0.25\cdot T_{D-2}+
                        0.125\cdot T_{D-3}}{1+0.5+0.25+0.125}

            with :math:`T_D` = Average temperature on the present day
                 :math:`T_{D-i}` = Average temperature on the day - i

            References
            ----------
            .. [1] `BDEW <https://www.avacon.de/cps/rde/xbcr/avacon/15-06-30_Leitfaden_Abwicklung_SLP_Gas.pdf>`_,
                BDEW Documentation for heat profiles.
            """

        # calculate daily mean temperature
        temperature = self.df["temperature"].resample('D').mean().reindex(
            self.df.index).fillna(method="ffill")

        if how == "geometric_series":
            temperature_mean = (
                temperature + 0.5 * np.roll(temperature, 24) +
                0.25 * np.roll(temperature, 48) +
                0.125 * np.roll(temperature, 72)) / 1.875
        elif how == "mean":
            temperature_mean = temperature
        else:
            temperature_mean = None

        return temperature_mean

    def get_temperature_interval(self):
        """Appoints the corresponding temperature interval to each temperature
        in the temperature vector.
        """
        intervals = ({
            -20: 1, -19: 1, -18: 1, -17: 1, -16: 1, -15: 1, -14: 2,
            -13: 2, -12: 2, -11: 2, -10: 2, -9: 3, -8: 3, -7: 3, -6: 3, -5: 3,
            -4: 4, -3: 4, -2: 4, -1: 4, 0: 4, 1: 5, 2: 5, 3: 5, 4: 5, 5: 5,
            6: 6, 7: 6, 8: 6, 9: 6, 10: 6, 11: 7, 12: 7, 13: 7, 14: 7, 15: 7,
            16: 8, 17: 8, 18: 8, 19: 8, 20: 8, 21: 9, 22: 9, 23: 9, 24: 9,
            25: 9, 26: 10, 27: 10, 28: 10, 29: 10, 30: 10, 31: 10, 32: 10,
            33: 10, 34: 10, 35: 10, 36: 10, 37: 10, 38: 10, 39: 10, 40: 10})

        temperature_rounded = [ceil(i) for i in self.df['temperature_geo']]

        temperature_interval = [intervals[i] for i in temperature_rounded]

        return np.transpose(np.array(temperature_interval))

    def get_sf_values(self, filename="shlp_hour_factors.csv"):
        """ Determine the h-values

        Parameters
        ----------
        filename : string
            name of file where sigmoid factors are stored
        """
        file = os.path.join(self.datapath, filename)
        hour_factors = pd.read_csv(file, index_col=0)
        hour_factors = hour_factors.query(
            'building_class=={0} and shlp_type=="{1}"'
            .format(self.building_class, self.shlp_type))

        # Join the two DataFrames on the columns 'hour' and 'hour_of_the_day'
        # or ['hour' 'weekday'] and ['hour_of_the_day', 'weekday'] if it is
        # not a residential slp.
        residential = self.building_class > 0
        left_cols = ['hour_of_day'] + (['weekday'] if not residential else [])
        right_cols = ['hour'] + (['weekday'] if not residential else [])
        sf_mat = pd.DataFrame.merge(
            hour_factors, self.df, left_on=left_cols, right_on=right_cols,
            how='outer', left_index=True).sort_index()

        # drop unnecessary columns
        drop_cols = (
            ['hour_of_day', 'hour', 'building_class', 'shlp_type',
             'date', 'temperature'] + (['weekday_x'] if residential else []) +
            (['weekday_y'] if residential else []) +
            (['weekday'] if not residential else []))
        sf_mat = sf_mat.drop(drop_cols, 1)

        # Determine the h values
        sf = (np.array(sf_mat)[np.array(list(range(0, 8760)))[:],
              (self.get_temperature_interval() - 1)[:]])
        return np.array(list(map(float, sf[:])))

    def get_sigmoid_parameters(self, filename="shlp_sigmoid_factors.csv"):
        """ Retrieve the sigmoid parameters from csv-files

        Parameters
        ----------
        filename : string
            name of file where sigmoid factors are stored
        """

        file = os.path.join(self.datapath, filename)
        sigmoid = pd.read_csv(file, index_col=0)
        sigmoid = sigmoid.query(
            'building_class=={0} and '.format(self.building_class) +
            'shlp_type=="{0}" and '.format(self.shlp_type) +
            'wind_impact=={0}'.format(self.wind_class))

        a = float(sigmoid['parameter_a'])
        b = float(sigmoid['parameter_b'])
        c = float(sigmoid['parameter_c'])
        if self.ww_incl:
            d = float(sigmoid['parameter_d'])
        else:
            d = 0
        return a, b, c, d

    def get_weekday_parameters(self, filename="shlp_weekday_factors.csv"):
        """ Retrieve the weekday parameter from csv-file

        Parameters
        ----------
        filename : string
            name of file where sigmoid factors are stored
        """
        file = os.path.join(self.datapath, filename)
        f_df = pd.read_csv(file, index_col=0)

        tmp_df = f_df.query('shlp_type=="{0}"'.format(self.shlp_type)).drop(
            'shlp_type', axis=1)

        tmp_df['weekdays'] = np.array(list(range(7))) + 1

        return np.array(list(map(float, pd.DataFrame.merge(
            tmp_df, self.df, left_on='weekdays', right_on='weekday',
            how='outer', left_index=True).sort_index()['wochentagsfaktor'])))

    def get_bdew_profile(self):
        """ Calculation of the hourly heat demand using the bdew-equations
        """
        self.df["temperature"] = self.temperature.values
        self.df["temperature_geo"] = self.weighted_temperature(
            how="geometric_series")

        sf = self.get_sf_values()

        [a, b, c, d] = self.get_sigmoid_parameters()

        f = self.get_weekday_parameters()
        h = (a / (1 + (b / (self.df["temperature_geo"] - 40)) ** c) + d)
        kw = self.annual_heat_demand / (sum(h * f) / 24)
        heat_profile = (kw * h * f * sf)

        return heat_profile
