# coding: utf-8

from __future__ import unicode_literals, division
import subprocess
import os
import shutil
import logging

import numpy as np

from monty.shutil import decompress_dir

from custodian.custodian import Job


"""
This module implements basic kinds of jobs for FHI-aims runs.
"""


logger = logging.getLogger(__name__)


__author__ = "Jan Kloppenburg"
__version__ = "0.0.1"
__maintainer__ = "jan Kloppenburg"
__email__ = "jank@numphys.org"
__status__ = "Beta"
__date__ = "4Aug2019"

AIMS_INPUT_FILES = {'control.in', 'geometry.in'}

AIMS_OUTPUT_FILES = ['geometry.in.next_step']


class AimsJob(Job):
    """
    A basic job. Just runs whatever is in the directory. But conceivably
    can be a complex processing of inputs etc. with initialization.
    """

    def __init__(self, aims_cmd, output_file="run",
                 stderr_file="std_err.txt", suffix="", final=True,
                 backup=True, auto_continue=False):
        """
        This constructor is necessarily complex due to the need for
        flexibility. For standard kinds of runs, it's often better to use one
        of the static constructors. The defaults are usually fine too.

        Args:
            aims_cmd (str): Command to run aims as a list of args. For example,
                if you are using mpirun, it can be something like
                ["mpirun", "aims"]
            output_file (str): Name of file to direct standard out to.
                Defaults to "vasp.out".
            stderr_file (str): Name of file to direct standard error to.
                Defaults to "std_err.txt".
            suffix (str): A suffix to be appended to the final output. E.g.,
                to rename all output from say s.out to
                s.out.relax1, provide ".relax1" as the suffix.
            final (bool): Indicating whether this is the final job in a
                series. Defaults to True.
            backup (bool): Whether to backup the initial input files. If True,
                the control.in and geometry.in will be copied with a
                ".orig" appended. Defaults to True.
        """
        self.aims_cmd = aims_cmd
        self.output_file = output_file
        self.stderr_file = stderr_file
        self.final = final
        self.backup = backup
        self.suffix = suffix
        self.auto_continue = auto_continue

    def setup(self):
        """
        Performs initial setup for AimsJob, including overriding any settings
        and backing up.
        """
        decompress_dir('.')
        actions = []

        if self.backup:
            for f in AIMS_INPUT_FILES:
                shutil.copy(f, "{}.orig".format(f))

        return actions

    def run(self):
        """
        Perform the actual run.

        Returns:
            (subprocess.Popen) Used for monitoring.
        """
        cmd = list(self.aims_cmd)
        logger.info("Running {}".format(" ".join(cmd)))
        with open(self.output_file, 'w') as f_std, open(self.stderr_file, "w", buffering=1) as f_err:
            # use line buffering for stderr
            p = subprocess.Popen(cmd, stdout=f_std, stderr=f_err)
        return p

    def postprocess(self):
        """
        Postprocessing includes renaming and gzipping where necessary.
        """
        for f in AIMS_OUTPUT_FILES + [self.output_file]:
            if os.path.exists(f):
                if self.final and self.suffix != "":
                    shutil.move(f, "{}{}".format(f, self.suffix))
                elif self.suffix != "":
                    shutil.copy(f, "{}{}".format(f, self.suffix))

        # Remove continuation so if a subsequent job is run in
        # the same directory, will not restart this job.
        if os.path.exists("continue.json"):
            os.remove("continue.json")

        scf = dict()
        i_step = 0

        parse_atoms = False
        parse_forces = False
        parse_stress = False

        with open('run', 'r') as f:
            for line in f:
                if '| Number of atoms' in line:
                    n_atoms = int(line.split()[5])
                if 'Begin self-consistency loop:' in line:
                    i_step += 1
                    i_atom = 0
                    i_force = 0
                    scf[i_step] = {'atoms': [], 'forces': [], 'lattice': [], 'stress': [],
                                   'species': [], 'energy': 0.0}
                if '| Total energy                  :' in line:
                    scf[i_step]['energy'] = float(line.split()[6])
                if parse_forces:
                    scf[i_step]['forces'].append([float(x) for x in line.split()[2:5]])
                    i_force += 1
                    if i_force == n_atoms:
                        parse_forces = False
                if 'Total atomic forces (unitary forces cleaned) [eV/Ang]:' in line:
                    parse_forces = True
                if parse_atoms:
                    if 'lattice' in line:
                        scf[i_step]['lattice'].append([float(x) for x in line.split()[1:4]])
                    elif len(line.split()) == 0:
                        continue
                    else:
                        scf[i_step]['atoms'].append([float(x) for x in line.split()[1:4]])
                        scf[i_step]['species'].append(line.split()[4])
                        i_atom += 1
                    if i_atom == n_atoms:
                        parse_atoms = False
                if 'x [A]             y [A]             z [A]' in line:
                    parse_atoms = True
                if parse_stress:
                    if '|  x       ' in line:
                        scf[i_step]['stress'].append([float(x) for x in line.split()[2:5]])
                    if '|  y       ' in line:
                        scf[i_step]['stress'].append([float(x) for x in line.split()[2:5]])
                    if '|  z       ' in line:
                        scf[i_step]['stress'].append([float(x) for x in line.split()[2:5]])
                    if '|  Pressure:' in line:
                        parse_stress = False
                if 'Analytical stress tensor - Symmetrized' in line:
                    parse_stress = True

        with open('parsed.xyz', 'w') as f:
            for i in range(1, len(scf) + 1):
                vol = np.abs(np.dot(scf[i]['lattice'][0], np.cross(scf[i]['lattice'][1], scf[i]['lattice'][2])))
                stress = np.array([[scf[i]['stress'][0][0], scf[i]['stress'][0][1], scf[i]['stress'][0][2]],
                                   [scf[i]['stress'][1][0], scf[i]['stress'][1][1], scf[i]['stress'][1][2]],
                                   [scf[i]['stress'][2][0], scf[i]['stress'][2][1], scf[i]['stress'][2][2]]])
                virial = - np.dot(vol, stress)
                f.write('{}\n'.format(n_atoms))
                f.write('Lattice="{:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f}" '
                        'Properties=species:S:1:pos:R:3:forces:R:3:force_mask:L:1'
                        ' virial="{:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f}" '
                        ' stress="{:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f}" '
                        ' free_energy={:6.6f} pbc="T T T"'
                        ' config_type=cluster\n'.format(
                            scf[i]['lattice'][0][0], scf[i]['lattice'][0][1], scf[i]['lattice'][0][2],
                            scf[i]['lattice'][1][0], scf[i]['lattice'][1][1], scf[i]['lattice'][1][2],
                            scf[i]['lattice'][2][0], scf[i]['lattice'][2][1], scf[i]['lattice'][2][2],
                            virial[0][0], virial[0][1], virial[0][2],
                            virial[1][0], virial[1][1], virial[1][2],
                            virial[2][0], virial[2][1], virial[2][2],
                            scf[i]['stress'][0][0], scf[i]['stress'][0][1], scf[i]['stress'][0][2],
                            scf[i]['stress'][1][0], scf[i]['stress'][1][1], scf[i]['stress'][1][2],
                            scf[i]['stress'][2][0], scf[i]['stress'][2][1], scf[i]['stress'][2][2],
                            scf[i]['energy']))

                for j in range(len(scf[i]['atoms'])):
                    f.write('{} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} {:6.6f} 0\n'.
                            format(scf[i]['species'][j],
                                   scf[i]['atoms'][j][0], scf[i]['atoms'][j][1], scf[i]['atoms'][j][2],
                                   scf[i]['forces'][j][0], scf[i]['forces'][j][1], scf[i]['forces'][j][2]))
                f.write('\n')

    @classmethod
    def tddft_run(cls, aims_cmd):
        """

        :param aims_cmd:
        :return:
        """

        pass

    @classmethod
    def full_opt_run(cls, aims_cmd, converged_forces=0.01, max_steps=10, **aims_job_kwargs):
        """
        Returns a generator of jobs for a full optimization run. Basically,
        this runs an infinite series of geometry optimization jobs until the
        structure is either below threshold or max_steps is reached.

        Args:
            aims_cmd (str): Command to run aims as a list of args. For example,
                if you are using mpirun, it can be something like
                ["mpirun", "aims.VERSION.scalapack.mpi"]
            max_steps (int): The maximum number of runs. Defaults to 10.

            **vasp_job_kwargs: Passthrough kwargs to AimsJob. See
                :class:`custodian.fhi_aims.jobs.AimsJob`.
        Returns:
            Generator of jobs.
        """

        converged_forces = converged_forces

        pass

        def get_force(output_file='run'):
            """
            Return the last force of the prievious run:

            :param output_file:
                File to parse

            :return:
                last computed total force
            """
            max_forces = []

            with open(output_file, 'rt') as f:
                for line in f:
                    if 'Maximum force component is' in line:
                        max_forces.append(float(line.split()[4]))
                    if 'Counterproductive step -> revert!' in line:
                        max_forces = max_forces[:-1]

            return np.amin(max_forces)

        yield AimsJob(aims_cmd, final=False, suffix=".relax%d" % (i+1), **aims_job_kwargs)
