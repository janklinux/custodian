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
__maintainer__ = "Shyue Ping Ong"
__email__ = "ongsp@ucsd.edu"
__status__ = "Beta"
__date__ = "2/4/13"

AIMS_BACKUP_FILES = {"run", "geometry.in.next_step"}


class AimsErrorHandler(ErrorHandler):
    """
    Master VaspErrorHandler class that handles a number of common errors
    that occur during VASP runs.
    """

    is_monitor = True

    error_msgs = {
        "energy_F_inconsistent": ["  ** Inconsistency of forces<->energy above specified tolerance."],
        'keyword_error': ['* Unknown keyword']}

    def __init__(self, output_filename="run", errors_subset_to_catch=None):
        """
        Initializes the handler with the output file to check.

        Args:
            output_filename (str): This is the file where the stdout for vasp
                is being redirected. The error messages that are checked are
                present in the stdout. Defaults to "vasp.out", which is the
                default redirect used by :class:`custodian.vasp.jobs.VaspJob`.

                ```
                subset = list(VaspErrorHandler.error_msgs.keys())
                subset.pop("eddrrm")
                handler = VaspErrorHandler(errors_subset_to_catch=subset)
                ```
        """
        self.output_filename = output_filename
        self.errors = set()
        self.error_count = Counter()
        self.errors_subset_to_catch = errors_subset_to_catch or list(AimsErrorHandler.error_msgs.keys())

        print(list(AimsErrorHandler.error_msgs.keys()))

    def check(self):
        self.errors = set()
        with open(self.output_filename, "r") as f:
            for line in f:
                for err, msgs in AimsErrorHandler.error_msgs.items():
                    if err in self.errors_subset_to_catch:
                        for msg in msgs:
                            if line.strip().find(msg) != -1:
                                self.errors.add(err)
        print('FOUND: ', self.errors)
        return len(self.errors) > 0

    def correct(self):
        backup(AIMS_BACKUP_FILES | {self.output_filename})
        actions = []

        if "energy_F_inconsistent" in self.errors:
            actions.append({'action': 'continue_relaxation'})

        if 'keyword_error' in self.errors:
            actions.append({'action': 'fizzle'})

        return {"errors": list(self.errors), "actions": actions}


class FrozenJobErrorHandler(ErrorHandler):
    """
    Detects an error when the output file has not been updated
    in timeout seconds. Changes ALGO to Normal from Fast
    """

    is_monitor = True

    def __init__(self, output_filename="run", timeout=21600):
        """
        Initializes the handler with the output file to check.

        Args:
            output_filename (str): This is the file where the stdout for vasp
                is being redirected. The error messages that are checked are
                present in the stdout. Defaults to "vasp.out", which is the
                default redirect used by :class:`custodian.vasp.jobs.VaspJob`.
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
