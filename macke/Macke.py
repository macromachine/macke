"""
Main container for all steps of the MACKE analysis
"""

from datetime import datetime
from multiprocessing import Pool
from progressbar import ProgressBar
from os import makedirs, path
import shutil
from time import sleep
from .CallGraph import CallGraph
from .config import THREADNUM
from .Klee import execute_klee
from .llvm_wrapper import encapsulate_symbolic


class Macke:

    def __init__(self, bitcodefile, parentdir="/tmp/macke", quiet=False):
        # Only accept valid files and directory
        assert(path.isfile(bitcodefile))

        # store the path to the analyzed bitcode file
        self.bitcodefile = bitcodefile

        # generate name of directory with all run results
        newdirname = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        self.rundir = path.join(parentdir, newdirname)

        # Generate the path for the bitcode directory
        self.bcdir = path.join(self.rundir, "bitcode")

        # Generate the filename for the copy of the program
        self.program_bc = path.join(self.rundir, "program.bc")

        # Internal counter for the number of klee runs
        self.kleecount = 1

        # Setting quiet == True suppress all outputs
        self.quiet = quiet

    def get_next_klee_directory(self):
        result = path.join(self.rundir, "klee-out-%d" % self.kleecount)
        self.kleecount += 1
        return result

    def run_complete_analysis(self):
        self.run_initialization()
        self.run_phase_one()
        self.run_phase_two()

    def run_initialization(self):
        # Create an empty run directory with empty bitcode directory
        makedirs(self.bcdir)

        # Copy the unmodified bitcode file
        shutil.copy2(self.bitcodefile, self.program_bc)

        # TODO copy current git hash of macke
        # TODO copy config file
        # TODO add self.bitcodefile information

        # Print some information for the user
        self.qprint(
            "Start analysis of %s in %s" % (self.bitcodefile, self.rundir))

    def run_phase_one(self):
        # Generate a call graph
        self.callgraph = CallGraph(self.bitcodefile)

        # Fill a list of functions for the symbolic encapsulation
        tasks = self.callgraph.get_candidates_for_symbolic_encapsulation()

        self.qprint("Phase 1: %d of %d functions are suitable for symbolic "
                    "encapsulation" % (len(tasks), len(self.callgraph.graph)))

        # Create a parallel pool with a process for each cpu thread
        pool = Pool(THREADNUM)

        # Storage for all complete runs
        kleedones = []

        # Dispense the KLEE runs on the workers in the pool
        for function in tasks:
            pool.apply_async(thread_phase_one, (
                function, self.program_bc, self.bcdir,
                self.get_next_klee_directory()
            ), callback=kleedones.append)

        # close the pool after all KLEE runs registered
        pool.close()

        if not self.quiet:
            # Keeping track of the progress until everything is done
            with ProgressBar(max_value=len(tasks)) as bar:
                while len(kleedones) != len(tasks):
                    bar.update(len(kleedones))
                    sleep(0.3)
                bar.update(len(kleedones))
        pool.join()

        # fill some counters
        self.testcases = sum(k.testcount for k in kleedones)
        self.errfunccount = sum(k.errorcount != 0 for k in kleedones)
        self.errtotalcount = sum(k.errorcount for k in kleedones)

        self.qprint("Phase 1: %d test cases generated. "
                    "Found %d total errors in %d functions" %
                    (self.testcases, self.errtotalcount, self.errfunccount))

        # TODO prepare them for phase two

    def run_phase_two(self):
        self.qprint("Phase 2: ... is not working ... yet ^^")

    def qprint(self, *args, **kwargs):
        if not self.quiet:
            print(*args, **kwargs)

    def delete_directory(self):
        shutil.rmtree(self.rundir, ignore_errors=True)


def thread_phase_one(functionname, program_bc, bcdir, outdir):
    """
    This function is executed by the parallel processes in phase one
    """

    # Build filename for the new bcfile generated by symbolic encapsulation
    encapsulated_bcfile = path.join(bcdir, "sym-" + functionname + ".bc")

    # Generate a bcfile with symbolic encapsulation as main function
    encapsulate_symbolic(program_bc, functionname, encapsulated_bcfile)

    # Run KLEE on it
    # TODO add relevant flags
    return execute_klee(encapsulated_bcfile, outdir, [])
