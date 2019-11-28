# coding: utf-8

from __future__ import unicode_literals, division

import os
import time
from collections import Counter

from custodian.custodian import ErrorHandler
from custodian.utils import backup

"""
This module implements specific error handlers for VASP runs. These handlers
tries to detect common errors in vasp runs and attempt to fix them on the fly
by modifying the input files.
"""

__author__ = "Shyue Ping Ong, William Davidson Richards, Anubhav Jain, " \
             "Wei Chen, Stephen Dacek, Jan Kloppenburg"
__version__ = "0.1"
__maintainer__ = "Jan Kloppenburg"
__email__ = "jank@numphys.org"
__status__ = "Beta"
__date__ = "4Aug2019"

AIMS_BACKUP_FILES = {"run", "geometry.in.next_step"}


class AimsRelaxHandler(ErrorHandler):
    """
    Master Handler class that handles a number of common errors and tunes
    """

    is_monitor = False
    is_terminating = False

    error_msgs = {
        "energy_F_inconsistent": ["** Inconsistency of forces<->energy above specified tolerance."],
        'keyword_error': ['* Unknown keyword']}

    def __init__(self, output_filename="run", errors_subset_to_catch=None):
        """
        Initializes the handler with the output file to check.

        Args:
            output_filename (str): This is the file where the stdout
                is being redirected. The error messages that are checked are
                present in the stdout. Defaults to "run", which is the
                default redirect used by :class:`custodian.fhi_aims.jobs.AimsJob`.
        """
        self.output_filename = output_filename
        self.errors = set()
        self.error_count = Counter()
        self.errors_subset_to_catch = errors_subset_to_catch or list(AimsRelaxHandler.error_msgs.keys())

    def check(self):
        self.errors = set()
        with open(self.output_filename, "r") as f:
            for line in f:
                for err, msgs in AimsRelaxHandler.error_msgs.items():
                    if err in self.errors_subset_to_catch:
                        for msg in msgs:
                            if line.strip().find(msg) != -1:
                                self.errors.add(err)
        return len(self.errors) > 0

    def correct(self):
        backup(AIMS_BACKUP_FILES | {self.output_filename})
        actions = []

        if "energy_F_inconsistent" in self.errors:
            os.rename('geometry.in.next_step', 'geometry.in')
            actions.append({'fixed': 'geo_step -> geo'})

        return {"errors": list(self.errors), "actions": actions}


class FrozenJobErrorHandler(ErrorHandler):
    """
    Detects an error when the output file has not been updated in timeout seconds, no fix for that
    """

    is_monitor = True

    def __init__(self, output_filename="run", timeout=3600):
        """
        Initializes the handler with the output file to check.

        Args:
            output_filename (str): This is the file where the stdout
                is being redirected. The error messages that are checked are
                present in the stdout.
            timeout (int): The time in seconds between checks where if there
                is no activity on the output file, the run is considered
                frozen. Defaults to 3600 seconds, i.e., 1 hour.
        """
        self.output_filename = output_filename
        self.timeout = timeout

    def check(self):
        st = os.stat(self.output_filename)
        if time.time() - st.st_mtime > self.timeout:
            return True

    def correct(self):
        backup(AIMS_BACKUP_FILES | {self.output_filename})
        actions = []
        return {"errors": ["Frozen job"], "actions": actions}


class ConvergenceEnhancer(ErrorHandler):
    """
    Monitors convergence progress and adjusts intermediate settings for:
            sc_accuracy_rho | sc_accuracy_eev | sc_accuracy_etot
    via control.update.in
    """

    is_monitor = True

    def __init__(self, output_filename='run', min_scf_steps=50):
        self.output_filename = output_filename
        self.min_scf_steps = min_scf_steps
        self.stage_224 = False
        self.stage_112 = False
        self.mod_count = 0
        self.t0 = time.time()
        self.settings_restored = False
        self.sc_rho = -1
        self.sc_eev = -1
        self.sc_tot = -1
        with open('control.in', 'r') as f:
            for line in f:
                if ' sc_accuracy_rho ' in line:
                    self.sc_rho = float(line.split()[1])
                if ' sc_accuracy_eev ' in line:
                    self.sc_eev = float(line.split()[1])
                if ' sc_accuracy_etot ' in line:
                    self.sc_tot = float(line.split()[1])
                if ' spin ' in line:
                    if line.split()[1] == 'collinear':
                        self.force_position = 14
                        self.is_collinear = True
                    else:
                        self.force_position = 13
                        self.is_collinear = False

    def check(self):
        if self.sc_rho == -1 or self.sc_eev == -1 or self.sc_tot == -1:
            with open('ERROR', 'w') as f:
                f.write('one of rho, eev or etot are not specified, ABORT')
            return True

        log_out = open('LOG_OUT', 'a+')

        log_out.write('LIST original parameters: rho: {:3.3e} | eev: {:3.3e} | etot: {:3.3e}\n'
                      .format(self.sc_rho, self.sc_eev, self.sc_tot))

        log_out.write('RUNTIME: {}\n'.format(time.time()-self.t0))

        scf_line = []
        with open(self.output_filename, 'r') as f:
            is_modified = -1
            is_converged = False
            for line in f:
                if "Finished reading input file 'control.update.in'" in line:
                    is_modified = True
                if is_modified and 'Self-consistency cycle converged.' in line:
                    is_converged = True
                if line.startswith('  SCF'):
                    if len(line.split()) > 10:
                        scf_line.append(line.strip())
                        if line.split()[self.force_position] != '.':
                            scf_line = []
                            is_modified = False

        rho_d = []
        rho_s = []
        eev = []
        etot = []
        if self.is_collinear:
            for line in scf_line:
                rho_d.append(float(line.split()[5]))
                rho_s.append(float(line.split()[6]))
                eev.append(float(line.split()[10]))
                etot.append(float(line.split()[12]))
        else:
            for line in scf_line:
                rho_d.append(float(line.split()[5]))
                eev.append(float(line.split()[9]))
                etot.append(float(line.split()[11]))

        log_out.write('MOD: {}\n'.format(self.mod_count))

        if self.settings_restored:
            log_out.write('RESTORED original parameters: rho: {:3.3e} | eev: {:3.3e} | etot: {:3.3e}\n'
                          .format(self.sc_rho, self.sc_eev, self.sc_tot))
            log_out.write('moving HELPER out of way...\n')
            os.rename('control.update.in', 'last_applied_update_parameters_which_converged')
            self.settings_restored = False

        if is_modified and os.path.isfile('control.update.in'):
            if self.stage_224 or self.stage_112:
                if not is_converged:
                    log_out.write('moving update.in outa teh weh\n')
                    os.rename('control.update.in', 'last_update_parameters')
                else:
                    with open('control.update.in', 'w') as f:
                        f.write('sc_accuracy_rho {:3.3e}\n'.format(self.sc_rho))
                        f.write('sc_accuracy_eev {:3.3e}\n'.format(self.sc_eev))
                        f.write('sc_accuracy_etot {:3.3e}'.format(self.sc_tot))
                    self.settings_restored = True
                    self.mod_count += 1
                    log_out.write('Number of modifications: {:2d}\n'.format(self.mod_count))

        if len(scf_line) < self.min_scf_steps:
            return False  # SKIP CHECK if less than n SCF cycles

        log_out.write('STEPS NOW 1: {}\n'.format(self.min_scf_steps))

        if all(rho_d) > self.sc_rho and all(eev) > self.sc_eev and all(etot) > self.sc_tot:
            log_out.write('non-convergent, needs fix {} {}\n'.format(self.stage_224, self.stage_112))
            if not self.stage_224 and not self.stage_112:
                with open('control.update.in', 'w') as f:
                    f.write('sc_accuracy_rho 1e-2\n')
                    f.write('sc_accuracy_eev 1e-2\n')
                    f.write('sc_accuracy_etot 1e-4')
                self.stage_224 = True
                self.min_scf_steps += 50
                log_out.write('STEPS NOW 2: {}\n'.format(self.min_scf_steps))
            elif self.stage_224 and not self.stage_112:
                with open('control.update.in', 'w') as f:
                    f.write('sc_accuracy_rho 1e-1\n')
                    f.write('sc_accuracy_eev 1e-1\n')
                    f.write('sc_accuracy_etot 1e-2')
                self.stage_112 = True
                self.min_scf_steps += 20
                log_out.write('STEPS NOW 3: {}\n'.format(self.min_scf_steps))
            elif self.stage_224 and self.stage_112:
                if self.is_collinear:
                    log_out.write('at this point manual intervantion is needed, please '
                                  'check the initial moments as a first improvement step\n')
                    # return True  # HARD ABORT - treat as Error as this point
                else:
                    log_out.write('handler out of choices, please implement more solutions...\n')
                    # return True  # HARD ABORT - treat as Error as this point

        log_out.close()

    def correct(self):
        backup(AIMS_BACKUP_FILES | {self.output_filename})
        actions = []
        return {"errors": ["Non-convergent"], "actions": actions}
