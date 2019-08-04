# coding: utf-8

from __future__ import unicode_literals, division

from custodian.custodian import Validator


class AimsConvergedValidator(Validator):
    """
    Inverse logic?
    """

    def __init__(self):
        pass

    def check(self):
        print('checking')

        with open('run', 'rt') as f:
            aims_out = f.readlines()

        converged = False
        for line in aims_out:
            if 'Have a nice day.' in line:
                converged = True

        return not converged
