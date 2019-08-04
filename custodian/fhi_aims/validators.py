# coding: utf-8

from __future__ import unicode_literals, division

from custodian.custodian import Validator


class AimsConvergedValidator(Validator):
    """
    Checks for convergence
    """

    def __init__(self):
        pass

    def check(self):
        converged = False
        try:
            with open('run', 'rt') as f:
                for line in f:
                    if 'Have a nice day.' in line:
                        converged = True
        except:
            return False
        return converged


class AimsSecondValidator(Validator):
    """
    """

    def __init__(self):
        pass

    def check(self):
        print('checking')

        with open('run', 'rt') as f:
            aims_out = f.readlines()

        print('READ: ', aims_out)

        converged = False
        for line in aims_out:
            print(line)
            if 'Have a nice day.' in line:
                converged = True

        return converged
