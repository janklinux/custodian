#!/usr/bin/env python

"""
This module implements error handlers for QChem runs. Currently tested only
for B3LYP DFT jobs.
"""

from __future__ import division
import glob
import json
import logging
import os
import re
import tarfile
from pymatgen.io.qchemio import QcOutput, QcInput, QcTask
from custodian.custodian import ErrorHandler

__author__ = "Xiaohui Qu"
__version__ = "0.1"
__maintainer__ = "Xiaohui Qu"
__email__ = "xhqu1981@gmail.com"
__status__ = "Alpha"
__date__ = "12/04/13"


class QChemErrorHandler(ErrorHandler):
    """
    Error handler for QChem Jobs. Currently tested only for B3LYP DFT jobs
    generated by pymatgen.
    """
    def __init__(self, input_file="mol.qcinp", output_file="mol.qcout",
                 ex_backup_list=(), rca_gdm_thresh=1.0E-3,
                 scf_max_cycles=200, geom_max_cycles=200, qchem_job=None):
        """
        Initializes the error handler from a set of input and output files.

        Args:
            input_file (str): Name of the QChem input file.
            output_file (str): Name of the QChem output file.
            ex_backup_list ([str]): List of the files to backup in addition
                to input and output file.
            rca_gdm_thresh (float): The threshold for the prior scf algorithm.
                If last deltaE is larger than the threshold try RCA_DIIS
                first, else, try DIIS_GDM first.
            scf_max_cycles (int): The max iterations to set to fix SCF failure.
            geom_max_cycles (int): The max iterations to set to fix geometry
                optimization failure.
            qchem_job (QchemJob): the managing object to run qchem.
        """
        self.input_file = input_file
        self.output_file = output_file
        self.ex_backup_list = ex_backup_list
        self.rca_gdm_thresh = rca_gdm_thresh
        self.scf_max_cycles = scf_max_cycles
        self.geom_max_cycles = geom_max_cycles
        self.outdata = None
        self.qcinp = None
        self.error_step_id = None
        self.errors = None
        self.fix_step = None
        self.qchem_job = qchem_job

    def check(self):
        # Checks output file for errors.
        self.outdata = QcOutput(self.output_file).data
        self.qcinp = QcInput.from_file(self.input_file)
        self.error_step_id = None
        self.errors = None
        self.fix_step = None
        for i, od in enumerate(self.outdata):
            if od["has_error"]:
                self.error_step_id = i
                self.fix_step = self.qcinp.jobs[i]
                self.errors = sorted(list(set(od["errors"])))
                return True
        return False

    def correct(self):
        self.backup()
        actions = []

        error_rankings = ("autoz error",
                          "No input text",
                          "NAN values",
                          "Bad SCF convergence",
                          "Geometry optimization failed",
                          "Exit Code 134",
                          "Molecular charge is not found",
                          "Molecular spin multipilicity is not found"
                          )
        e = self.errors[0]
        for prio_error in error_rankings:
            if prio_error in self.errors:
                e = prio_error
                break

        if e == "autoz error":
            if "sym_ignore" not in self.fix_step.params["rem"]:
                self.fix_step.disable_symmetry()
                actions.append("disable symmetry")
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "Bad SCF convergence":
            act = self.fix_scf()
            if act:
                actions.append(act)
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "Geometry optimization failed":
            act = self.fix_geom_opt()
            if act:
                actions.append(act)
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "NAN values":
            if "xc_grid" not in self.fix_step.params["rem"]:
                self.fix_step.set_dft_grid(128, 302)
                actions.append("use tighter grid")
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "No input text":
            if "sym_ignore" not in self.fix_step.params["rem"]:
                self.fix_step.disable_symmetry()
                actions.append("disable symmetry")
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "Exit Code 134":
            act = self.fix_error_code_134()
            if act:
                actions.append(act)
            else:
                return {"errors": self.errors, "actions": None}
        elif e == "Molecular charge is not found":
            return {"errors": self.errors, "actions": None}
        elif e == "Molecular spin multipilicity is not found":
            return {"errors": self.errors, "actions": None}
        else:
            return {"errors": self.errors, "actions": None}
        self.qcinp.write_file(self.input_file)
        return {"errors": self.errors, "actions": actions}

    def fix_error_code_134(self):
        if self.fix_step.params["rem"]["jobtype"] == "freq":
            if self.qchem_job.current_command_name != "half_cpus":
                self.qchem_job.select_command("half_cpus")
                return "half_cpus"
            else:
                return None
        elif "thresh" not in self.fix_step.params["rem"]:
            self.fix_step.set_integral_threshold(thresh=12)
            return "use tight integral threshold"
        elif self.qchem_job.current_command_name != "openmp":
            self.qchem_job.select_command("openmp")
            return "openmp"
        else:
            return None

    def fix_scf(self):
        comments = self.fix_step.params.get("comment", "")
        scf_pattern = re.compile(r"<SCF Fix Strategy>(.*)</SCF Fix "
                                 r"Strategy>", flags=re.DOTALL)
        old_strategy_text = re.findall(scf_pattern, comments)

        if len(old_strategy_text) > 0:
            old_strategy_text = old_strategy_text[0]
        od = self.outdata[self.error_step_id]

        if od["jobtype"] == "opt" and len(od["molecules"]) >= 2:
            strategy = "reset"
        elif len(old_strategy_text) > 0:
            strategy = json.loads(old_strategy_text)
            strategy["current_method_id"] += 1
        else:
            strategy = dict()
            if len(od["scf_iteration_energies"]) == 0 \
                    or len(od["scf_iteration_energies"][-1]) == 0:
                if 'Exit Code 134' in self.errors:
                    # SCF not started
                    if "thresh" not in self.fix_step.params["rem"]:
                        self.fix_step.set_integral_threshold(thresh=12)
                        return "use tight integral threshold"
                    else:
                        return None
                else:
                    return None
            scf_iters = od["scf_iteration_energies"][-1]
            if scf_iters[-1][1] >= self.rca_gdm_thresh:
                strategy["methods"] = ["increase_iter", "rca_diis", "gwh",
                                       "gdm", "rca", "core+rca"]
                strategy["current_method_id"] = 0
            else:
                strategy["methods"] = ["increase_iter", "diis_gdm", "gwh",
                                       "rca", "gdm", "core+gdm"]
                strategy["current_method_id"] = 0

        # noinspection PyTypeChecker
        if strategy == "reset":
            self.fix_step.set_scf_algorithm_and_iterations(
                algorithm="diis", iterations=self.scf_max_cycles)
            if "scf_guess" in self.fix_step.params["rem"]:
                self.fix_step.set_scf_initial_guess("sad")
            self.fix_step.mol = od["molecules"][-1]
            if self.fix_step.charge is None:
                self.fix_step.charge = self.fix_step.mol.charge
            if self.fix_step.spin_multiplicity is None:
                self.fix_step.spin_multiplicity = \
                    self.fix_step.mol.spin_multiplicity
            if len(old_strategy_text) > 0:
                comments = scf_pattern.sub("", comments)
                self.fix_step.params["comment"] = comments
            return "reset"
        elif strategy["current_method_id"] > len(strategy["methods"])-1:
            return None
        else:
            # noinspection PyTypeChecker
            method = strategy["methods"][strategy["current_method_id"]]
            if method == "increase_iter":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="diis", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
            elif method == "rca_diis":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="rca_diis", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
            elif method == "gwh":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="diis", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("gwh")
            elif method == "gdm":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="gdm", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
            elif method == "rca":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="rca", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
            elif method == "core+rca":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="rca", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("core")
            elif method == "diis_gdm":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="diis_gdm", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
            elif method == "core+gdm":
                self.fix_step.set_scf_algorithm_and_iterations(
                    algorithm="gdm", iterations=self.scf_max_cycles)
                self.fix_step.set_scf_initial_guess("sad")
                self.fix_step.set_scf_initial_guess("core")
            else:
                raise ValueError("fix method " + method + " is not supported")
            strategy_text = "<SCF Fix Strategy>"
            strategy_text += json.dumps(strategy, indent=4, sort_keys=True)
            strategy_text += "</SCF Fix Strategy>"
            if len(old_strategy_text) > 0:
                comments = scf_pattern.sub(strategy_text, comments)
            else:
                comments = strategy_text
            self.fix_step.params["comment"] = comments
            return method

    def fix_geom_opt(self):
        comments = self.fix_step.params.get("comment", "")
        geom_pattern = re.compile(r"<Geom Opt Fix Strategy>(.*)"
                                  r"</Geom Opt Fix Strategy>",
                                  flags=re.DOTALL)
        old_strategy_text = re.findall(geom_pattern, comments)

        if len(old_strategy_text) > 0:
            old_strategy_text = old_strategy_text[0]

        od = self.outdata[self.error_step_id]
        if len(old_strategy_text) > 0:
            strategy = json.loads(old_strategy_text)
            strategy["current_method_id"] += 1
        else:
            strategy = dict()
            strategy["methods"] = ["increase_iter", "GDIIS", "CartCoords"]
            strategy["current_method_id"] = 0
        if strategy["current_method_id"] > len(strategy["methods"]) - 1:
            return None
        else:
            method = strategy["methods"][strategy["current_method_id"]]
            if method == "increase_iter":
                self.fix_step.set_geom_max_iterations(self.geom_max_cycles)
                self.fix_step.mol = od["molecules"][-1]
                if self.fix_step.charge is None:
                    self.fix_step.charge = self.fix_step.mol.charge
                if self.fix_step.spin_multiplicity is None:
                    self.fix_step.spin_multiplicity = \
                        self.fix_step.mol.spin_multiplicity
            elif method == "GDIIS":
                self.fix_step.set_geom_opt_use_gdiis(subspace_size=5)
                self.fix_step.set_geom_max_iterations(self.geom_max_cycles)
                self.fix_step.mol = od["molecules"][-1]
                if self.fix_step.charge is None:
                    self.fix_step.charge = self.fix_step.mol.charge
                if self.fix_step.spin_multiplicity is None:
                    self.fix_step.spin_multiplicity = \
                        self.fix_step.mol.spin_multiplicity
            elif method == "CartCoords":
                self.fix_step.set_geom_opt_coords_type("cartesian")
                self.fix_step.set_geom_max_iterations(self.geom_max_cycles)
                self.fix_step.set_geom_opt_use_gdiis(0)
                self.fix_step.mol = od["molecules"][-1]
                if self.fix_step.charge is None:
                    self.fix_step.charge = self.fix_step.mol.charge
                if self.fix_step.spin_multiplicity is None:
                    self.fix_step.spin_multiplicity = \
                        self.fix_step.mol.spin_multiplicity
            else:
                raise ValueError("fix method" + method + "is not supported")
            strategy_text = "<Geom Opt Fix Strategy>"
            strategy_text += json.dumps(strategy, indent=4, sort_keys=True)
            strategy_text += "</Geom Opt Fix Strategy>"
            if len(old_strategy_text) > 0:
                comments = geom_pattern.sub(strategy_text, comments)
            else:
                comments = strategy_text
            self.fix_step.params["comment"] = comments
            return method

    def backup(self):
        error_num = max([0] + [int(f.split(".")[1])
                               for f in glob.glob("error.*.tar.gz")])
        filename = "error.{}.tar.gz".format(error_num + 1)
        logging.info("Backing up run to {}.".format(filename))
        tar = tarfile.open(filename, "w:gz")
        bak_list = [self.input_file, self.output_file] + \
            list(self.ex_backup_list)
        for f in bak_list:
            if os.path.exists(f):
                tar.add(f)
        tar.close()

    @property
    def to_dict(self):
        return {"@module": self.__class__.__module__,
                "@class": self.__class__.__name__,
                "input_file": self.input_file,
                "output_file": self.output_file,
                "ex_backup_list": self.ex_backup_list,
                "rca_gdm_thresh": self.rca_gdm_thresh,
                "scf_max_cycles": self.scf_max_cycles,
                "geom_max_cycles": self.geom_max_cycles,
                "outdata": self.outdata,
                "qcinp": self.qcinp.to_dict,
                "error_step_id": self.error_step_id,
                "errors": self.errors,
                "fix_step": self.fix_step.to_dict}

    @classmethod
    def from_dict(cls, d):
        h = QChemErrorHandler(input_file=d["input_file"],
                              output_file=d["output_file"],
                              ex_backup_list=d["ex_backup_list"],
                              rca_gdm_thresh=d["rca_gdm_thresh"],
                              scf_max_cycles=d["scf_max_cycles"],
                              geom_max_cycles=d["geom_max_cycles"])
        h.outdata = d["outdata"]
        h.qcinp = QcInput.from_dict(d["qcinp"])
        h.error_step_id = d["error_step_id"]
        h.errors = d["errors"]
        h.fix_step = QcTask.from_dict(d["fix_step"])
        return h