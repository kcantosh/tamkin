# -*- coding: utf-8 -*-
# TAMkin is a post-processing toolkit for normal mode analysis, thermochemistry
# and reaction kinetics.
# Copyright (C) 2008-2012 Toon Verstraelen <Toon.Verstraelen@UGent.be>, An Ghysels
# <An.Ghysels@UGent.be> and Matthias Vandichel <Matthias.Vandichel@UGent.be>
# Center for Molecular Modeling (CMM), Ghent University, Ghent, Belgium; all
# rights reserved unless otherwise stated.
#
# This file is part of TAMkin.
#
# TAMkin is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# In addition to the regulations of the GNU General Public License,
# publications and communications based in parts on this program or on
# parts of this program are required to cite the following article:
#
# "TAMkin: A Versatile Package for Vibrational Analysis and Chemical Kinetics",
# An Ghysels, Toon Verstraelen, Karen Hemelsoet, Michel Waroquier and Veronique
# Van Speybroeck, Journal of Chemical Information and Modeling, 2010, 50,
# 1736-1750W
# http://dx.doi.org/10.1021/ci100099g
#
# TAMkin is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>
#
#--


from tamkin.data import Molecule

from molmod import electronvolt, angstrom, amu
from molmod.periodic import periodic
from molmod.unit_cells import UnitCell

import numpy as np


__all__ = ["load_molecule_vasp", "load_fixed_vasp"]


def load_molecule_vasp(contcar, outcar_freq, outcar_energy=None, energy=None, multiplicity=1, is_periodic=True):
    """Load a molecule from VASP 4.6.X and 5.3.X output files

       Arguments:
        | contcar  --  A CONTCAR file with the structure used as POSCAR file for the
                       Hessian/frequency calculation in VASP. Do not use the CONTCAR file
                       generated by the frequency calculation. Use the CONTCAR from the
                       preceding geometry optimization instead.
        | outcar_freq  --  The OUTCAR file of the Hessian/frequency calculation. Also the
                           gradient and the energy are read from this file. The energy
                           without entropy (but not the extrapolation to sigma=0) is used.

       Optional arguments:
        | outcar_energy  --  When given, the (first) energy without entropy is read from
                             this file (not the extrapolation to sigma=0) instead of
                             reading the energy from the freq output
        | energy  --  The potential energy, which overrides the contents of outcar_freq.
        | multiplicity  --  The spin multiplicity of the electronic system
                            [default=1]
        | is_periodic  --  True when the system is periodic in three dimensions.
                           False when the systen is nonperiodic. [default=True].
    """
    # auxiliary function to read energy:
    def read_energy_without_entropy(f):
        # Go to the first energy
        for line in f:
            if line.startswith('  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)'):
                break
        # Skip three lines and read energy
        f.next()
        f.next()
        f.next()
        return float(f.next().split()[3])*electronvolt

    # Read atomic symbols, coordinates and cell vectors from CONTCAR
    symbols = []
    coordinates = []
    with open(contcar) as f:
        # Skip title.
        f.next().strip()

        # Read scale for rvecs.
        rvec_scale = float(f.next())
        # Read rvecs. VASP uses one row per cell vector.
        rvecs = np.fromstring(f.next()+f.next()+f.next(), sep=' ').reshape(3, 3)
        rvecs *= rvec_scale*angstrom
        unit_cell = UnitCell(rvecs)

        # Read symbols
        unique_symbols = f.next().split()
        # Read atom counts per symbol
        symbol_counts = [int(w) for w in f.next().split()]
        assert len(symbol_counts) == len(unique_symbols)
        natom = sum(symbol_counts)
        # Construct array with atomic numbers.
        numbers = []
        for iunique in xrange(len(unique_symbols)):
            number = periodic[unique_symbols[iunique]].number
            numbers.extend([number]*symbol_counts[iunique])
        numbers = np.array(numbers)

        # Check next line
        while f.next() != 'Direct\n':
            continue

        # Load fractional coordinates
        fractional = np.zeros((natom, 3), float)
        for iatom in xrange(natom):
            words = f.next().split()
            fractional[iatom, 0] = float(words[0])
            fractional[iatom, 1] = float(words[1])
            fractional[iatom, 2] = float(words[2])
        coordinates = unit_cell.to_cartesian(fractional)

    if outcar_energy is not None and energy is None:
        with open(outcar_energy) as f:
            energy = read_energy_without_entropy(f)

    # Read energy, gradient, Hessian and masses from outcar_freq. Note that the first
    # energy/force calculation is done on the unperturbed input structure.
    with open(outcar_freq) as f:
        # Loop over the POTCAR sections in the OUTCAR file
        number = None
        masses = np.zeros(natom, float)
        while True:
            line = f.next()
            if line.startswith('   VRHFIN ='):
                symbol = line[11:line.find(':')].strip()
                number = periodic[symbol].number
            elif line.startswith('   POMASS ='):
                mass = float(line[11:line.find(';')])*amu
                masses[numbers==number] = mass
            elif number is not None and line.startswith('------------------------------'):
                assert masses.min() > 0
                break

        # Go to the first gradient
        for line in f:
            if line.startswith(' POSITION'):
                break
        # Skip one line and read the gradient
        f.next()
        gradient = np.zeros((natom, 3), float)
        gunit = electronvolt/angstrom
        for iatom in xrange(natom):
            words = f.next().split()
            gradient[iatom, 0] = -float(words[3])*gunit
            gradient[iatom, 1] = -float(words[4])*gunit
            gradient[iatom, 2] = -float(words[5])*gunit

        if energy is None:
            energy = read_energy_without_entropy(f)

        # Go to the second derivatives
        for line in f:
            if line.startswith(' SECOND DERIVATIVES (NOT SYMMETRIZED)'):  break

        # Skip one line.
        f.next()

        # Load free atoms (not fixed in space).
        keys = f.next().split()
        nfree_dof = len(keys)
        indices_free = [3*int(key[:-1])+{'X': 0, 'Y': 1, 'Z': 2}[key[-1]]-3 for key in keys]
        assert nfree_dof % 3 == 0

        # Load the actual Hessian
        hunit = electronvolt/angstrom**2
        hessian = np.zeros((3*natom, 3*natom), float)
        for ifree0 in xrange(nfree_dof):
            line = f.next()
            irow = indices_free[ifree0]
            # skip first col
            words = line.split()[1:]
            assert len(words) == nfree_dof
            for ifree1 in xrange(nfree_dof):
                icol = indices_free[ifree1]
                hessian[irow, icol] = -float(words[ifree1])*hunit

        # Symmetrize the Hessian
        hessian = 0.5*(hessian + hessian.T)

    return Molecule(
        numbers, coordinates, masses, energy, gradient, hessian,
        multiplicity=multiplicity, periodic=is_periodic, unit_cell=unit_cell)


def load_fixed_vasp(filename):
    """ Load list of fixed atoms from VASP output file

    Argument:
     | filename  --  Filename of VASP output file (OUTCAR)

    VASP can calculate partial Hessians: only a submatrix of the complete Hessian
    is computed with numerical differentiation. The rest of the Hessian elements
    is put to zero. This function determines which atoms have zero rows/cols in
    the Hessian, or, in other words, which were fixed.
    """
    # Read data from out-VASP-file OUTCAR
    f = open(filename)

    # number of atoms (N)
    for line in f:
        if line.strip().startswith("Dimension of arrays:"):  break
    f.next()
    for line in f:
        words = line.split()
        N = int(words[-1])
        break

    # hessian, not symmetrized, useful to find indices of Hessian elements
    for line in f:
        if line.strip().startswith("SECOND DERIVATIVES (NOT SYMMETRIZED)"):  break
    f.next()
    for line in f:
        Nfree = len(line.split())/3   # nb of non-fixed atoms
        break
    # find the non-fixed atoms
    atoms_free = []
    row = 0
    mu = 0
    for line in f:
        if mu==0:
            atom = int(line.split()[0][:-1])
            atoms_free.append(atom-1)
        mu+=1
        row+=1
        if mu >= 3: mu=0
        if row >= 3*Nfree: break
    f.close()

    fixed_atoms = [at for at in xrange(N) if at not in atoms_free]
    return np.array(fixed_atoms)
