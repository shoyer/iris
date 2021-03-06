# (C) British Crown Copyright 2012 - 2013, Met Office
#
# This file is part of Iris.
#
# Iris is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Iris is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Iris.  If not, see <http://www.gnu.org/licenses/>.
"""
Provides ABF (and ABL) file format capabilities.

ABF and ABL files are satellite file formats defined by Boston University.
Including this module adds ABF and ABL loading to the session's capabilities.

The documentation for this file format can be found
`here <http://cliveg.bu.edu/modismisr/lai3g-fpar3g.html>`_.

"""

import calendar
import datetime
import glob
import os.path

import numpy as np
import numpy.ma as ma

import iris
from iris.coords import AuxCoord, DimCoord
from iris.coord_systems import GeogCS
import iris.fileformats
import iris.io.format_picker


X_SIZE = 4320
Y_SIZE = 2160


month_numbers = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


class ABFField(object):
    """
    A data field from an ABF (or ABL) file.

    Capable of creating a :class:`~iris.cube.Cube`.

    """
    def __init__(self, filename):
        """
        Create an ABFField object from the given filename.

        Args:

            * filename - An ABF filename.

        Example::

            field = ABFField("AVHRRBUVI01.1985feba.abl")

        """
        basename = os.path.basename(filename)
        if len(basename) != 24:
            raise ValueError("ABFField expects a filename of 24 characters: "
                             "{}".format(basename))
        self._filename = filename

    def __getattr__(self, key):
        # Do we need to load now?
        if not hasattr(self, "data"):
            self._read()
        try:
            return self.__dict__[key]
        except KeyError:
            raise AttributeError("ABFField has no attribute '{}'".format(key))

    def _read(self):
        """Read the field from the given filename."""
        basename = os.path.basename(self._filename)
        self.version = int(basename[9:11])
        self.year = int(basename[12:16])
        self.month = basename[16:19]
        self.period = basename[19:20]
        self.format = basename[21:24]

        self.month = month_numbers[self.month]

        # Data is 8 bit bigendian.
        self.data = np.fromfile(self._filename, dtype='>u1').reshape(X_SIZE,
                                                                     Y_SIZE)
        # Iris' preferred dimensional ordering is (y,x).
        self.data = self.data.transpose()
        # Flip, for a positive step through the Y dimension.
        self.data = self.data[::-1]
        # Any percentages greater than 100 represent missing data.
        self.data = ma.masked_greater(self.data, 100)
        # The default fill value is 999999(!), so we choose something
        # more sensible. NB. 999999 % 256 = 63 = bad.
        self.data.fill_value = 255

    def to_cube(self):
        """Return a new :class:`~iris.cube.Cube` from this ABFField."""

        cube = iris.cube.Cube(self.data)

        # Name.
        if self.format.lower() == "abf":
            cube.rename("leaf_area_index")
        elif self.format.lower() == "abl":
            cube.rename("FAPAR")
        else:
            msg = "Unknown ABF/ABL format: {}".format(self.format)
            raise iris.exceptions.TranslationError(msg)
        cube.units = "%"

        # Grid.
        step = 1.0 / 12.0

        llcs = GeogCS(semi_major_axis=6378137.0, semi_minor_axis=6356752.31424)

        x_coord = DimCoord(np.arange(X_SIZE) * step + (step / 2) - 180,
                           standard_name="longitude", units="degrees",
                           coord_system=llcs)

        y_coord = DimCoord(np.arange(Y_SIZE) * step + (step / 2) - 90,
                           standard_name="latitude",  units="degrees",
                           coord_system=llcs)

        x_coord.guess_bounds()
        y_coord.guess_bounds()

        cube.add_dim_coord(x_coord, 1)
        cube.add_dim_coord(y_coord, 0)

        # Time.
        if self.period == "a":
            start = 1
            end = 15
        elif self.period == "b":
            start = 16
            end = calendar.monthrange(self.year, self.month)[1]
        else:
            raise iris.exceptions.TranslationError("Unknown period: "
                                                   "{}".format(self.period))

        start = datetime.date(year=self.year, month=self.month, day=start)
        end = datetime.date(year=self.year, month=self.month, day=end)

        # Convert to "days since 0001-01-01".
        # Iris will have proper datetime objects in the future.
        # This step will not be necessary.
        start = start.toordinal() - 1
        end = end.toordinal() - 1

        # TODO: Should we put the point in the middle of the period instead?
        cube.add_aux_coord(AuxCoord(start, standard_name="time",
                                    units="days since 0001-01-01",
                                    bounds=[start, end]))

        # TODO: Do they only come from Boston?
        # Attributes.
        cube.attributes["source"] = "Boston University"

        return cube


def load_cubes(filespecs, callback=None):
    """
    Loads cubes from a list of ABF filenames.

    Args:

    * filenames - list of ABF filenames to load

    Kwargs:

    * callback - a function that can be passed to :func:`iris.io.run_callback`

    .. note::

        The resultant cubes may not be in the same order as in the file.

    """
    if isinstance(filespecs, basestring):
        filespecs = [filespecs]

    for filespec in filespecs:
        for filename in glob.glob(filespec):

            field = ABFField(filename)
            cube = field.to_cube()

            # Were we given a callback?
            if callback is not None:
                cube = iris.io.run_callback(callback, cube, field, filename)
                if cube is None:
                    continue

            yield cube
