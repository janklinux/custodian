# coding: utf-8

from __future__ import unicode_literals, division

import os

from custodian.custodian import Validator


class AimsConvergedValidator(Validator):
    """
    Inverse logic?
    """

    def __init__(self):
        pass

    def check(self):
        with open('run', 'rt') as f:
            aims_out = f.readlines()

        converged = False
        for line in aims_out:
            if 'Have a nice day.' in line:
                converged = True

        return not converged


class AimsTDDFTValidator(Validator):
    """
    Inverse logic?
    """

    def __init__(self):
        pass

    def check(self):
        req_files = ['TDDFT_LR_Spectrum_Singlet.dat', 'TDDFT_LR_Spectrum_Triplet.dat']
        for file in req_files:
            if os.path.isfile(file):
                return False
        return True
