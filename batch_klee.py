import time
import sys
import os
import glob
from optparse import OptionParser, OptionGroup
import re
from source_coverage import source_coverage
from compose_units import get_top_level_funcs, get_outlier_funcs
from read_ktest import generate_assert_code, get_location_to_insert, modify_unit_files, get_lines_to_insert
from second_klee_round import get_target_info

if __name__=='__main__':
    klee_command = 'klee --simplify-sym-indices --write-cov --write-smt2s --output-module --max-memory=1000 --disable-inlining --optimize --use-forked-solver --use-cex-cache --libc=uclibc --posix-runtime --allow-external-sym-calls --only-output-states-covering-new -max-sym-array-size=4096 -max-instruction-time=%d. --max-time=%d. --watchdog --max-memory-inhibit=false --max-static-fork-pct=1 -max-static-solve-pct=1 --max-static-cpfork-pct=1 --switch-type=internal --randomize-fork --search=nurs:covnew --use-batching-search --batch-instructions=10000 '%(10, 120)
    klee_executable = ' ./bzip2 '
    klee_sym_args = ' --sym-args 1 2 100 --sym-files 1 100'
    decl_vars = []
    func_nodes = []

    inj_code = []
    func_names = []

    sp_comps = []

    parser = OptionParser("usage: %prog -d {directory containing source files} -e {executable name}")
    parser.add_option('-d', '--dir', action='store', type='string', dest='dir', help='Source file directory path')
    parser.add_option('-e', '--exec', action='store', type='string', dest='executable', help='Name of executable generated by Makefile')
    parser.add_option('-n', '--n-long', action='store', type='int', dest='n_long', help='Minimum length of error chain to be reported')
    parser.add_option('-x', '--no-klee', action='store_true', dest='no_klee', help='Do not run KLEE, but only run the compositional analysis on the ptr.err files')
    parser.add_option('-s', '--special-components', action='store', type = 'string', dest='special_components_filename', help='Name of the file containing list of special components, to be considered strictly for compositional analysis')
    parser.add_option('-a', '--generate-assertion-code', action='store_true', dest='assert_code_needed', help='Generate instrumentation code for assertion statements')
    (opts, args) = parser.parse_args()

    # pprint(('diags', map(get_diag_info, tu.diagnostics)))

    dir_name = opts.dir
    exec_name = opts.executable
    no_klee = opts.no_klee
    assert_code_needed = opts.assert_code_needed
    if opts.special_components_filename:
        special_components_filename = opts.special_components_filename
    else:
        special_components_filename = ''
    
    if opts.n_long:
        n_long = opts.n_long
    else:
        n_long = 2

    if not special_components_filename=='':
        if not os.path.isfile(special_components_filename):
            print 'The file containing special components does not exist.\nExiting'
            sys.exit(-1)
        sp_comps_file = open(special_components_filename, 'r')
        for line in sp_comps_file:
            sp_comps.append(line.strip())

    if not os.path.isdir(dir_name):
        print 'Could not find the specified directory.\nExiting.'
        sys.exit(-1)

    if not dir_name.endswith('/'):
        dir_name = dir_name+'/'

    uncompiled_files = open(dir_name + 'incomplete.units', 'w')
    if not no_klee:
        for ud in glob.glob(dir_name+'*_units/'):
            main_pattern = dir_name+'(.*)_units/'
            main_match = re.search(main_pattern, ud)
            main_name = main_match.group(1)
            for f in glob.glob(ud+'*_*.c.units'):
                re_pattern = ud+'(.*)_(.*)\.c\.units'
                re_match = re.search(re_pattern, f)
                #main_file = re_match.group(1)
                func_name = re_match.group(2)

                if not os.path.exists(dir_name+main_name+'.c.bkp'):
                    os.system('cp '+dir_name+main_name+'.c ' + dir_name+main_name+'.c.bkp')
                os.system('cp '+f+' '+dir_name+main_name+'.c')
                
                os.system('make -C '+dir_name+' clean')
                make_ret = os.system('make -C '+dir_name+'../')

                if not make_ret==0:
                    uncompiled_files.write(f + '\n')
                    print 'Make error\nContinuing with the next unit file...\n'
                    time.sleep(3)
                    #user_input = raw_input('Make error')
                    continue

                # link_return = os.system('llvm-link-3.4 -o '+dir_name+exec_name+' '+dir_name+'*.bc')
                
                #if not link_return==0:
                #    user_input = raw_input('Linking error')
                #    continue
                

                os.system(klee_command + '--output-dir=' + ud + main_name + '_' + func_name + '/ ' + dir_name+main_name + ' ' + klee_sym_args)
            os.system('mv ' + dir_name + main_name + '.c.bkp ' + dir_name + main_name + '.c')

    uncompiled_files.close()

    tot_cov = 0
    tot_seen = 0
    for c_filename in glob.glob(dir_name + '*.c'):
        cov, seen = source_coverage(c_filename)
        tot_cov += len(cov)
        tot_seen += len(seen)

    coverage = float(tot_cov)/tot_seen
    src_cov_file = open(dir_name + 'src.cov', 'w+')
    src_cov_file.write(str(coverage))
    src_cov_file.close()

    composition_file = open(dir_name+'composition.test', 'w+')
    all_funcs = []
    affected_funcs = []
    unaffected_funcs = []
    for c_filename in glob.glob(dir_name + '*.c'):
        re_pattern = dir_name + '(.*).c'
        re_match = re.search(re_pattern, c_filename)
        main_name = re_match.group(1)

        for unit_test in glob.glob(dir_name+main_name+'_units/*.c.units'):
            unit_file_name = os.path.splitext(os.path.basename(unit_test))[0][:-2]
            func_name = unit_file_name.split('_', 1)[1]
            affected_parent_funcs, unaffected_parent_funcs = get_top_level_funcs(c_filename, func_name)
            if len(affected_parent_funcs)>=n_long or func_name in sp_comps:
                affected_funcs.extend(affected_parent_funcs)
                composition_file.write(func_name+'\n')
                composition_file.write(str(affected_parent_funcs)+'\n\n')
            if len(affected_parent_funcs)>0:
                all_funcs.extend(affected_parent_funcs)
            unaffected_funcs.extend(unaffected_parent_funcs)
    sorted_unaffected_funcs = []
    for uf in unaffected_funcs:
        if uf not in sorted_unaffected_funcs:
            sorted_unaffected_funcs.append(uf)
    unaffected_funcs = sorted_unaffected_funcs

    outliers = get_outlier_funcs(all_funcs)
    for o in outliers:
        if o not in affected_funcs:
            composition_file.write(o[1]+'\n')
            composition_file.write(str(o)+'\n\n')

    # Generate target information to use for targeted path search in KLEE
    target_info_file = open(dir_name + 'target.info', 'w+')
    for uf in unaffected_funcs:
        caller_file = uf[1]
        callee_lines = get_lines_to_insert([(uf[1], uf[2])], uf[0])
        if callee_lines:
            callee_line = callee_lines[0][2]
            target_info_file.write(caller_file + '\n' + str(callee_line+1) + '\n' + uf[2] + '\n\n')
    target_info_file.close()
    
    target_info = get_target_info(dir_name)

    # Generate assertion code that must be inserted manually into parent functions
    if assert_code_needed:
        for ktest_folder in glob.glob(dir_name + '*_units/*/'):
            memcpy_stmt, buffer_decl_stmt, comparison_stmt = generate_assert_code(ktest_folder)
            if not buffer_decl_stmt=='':
                assertion_code_file = open(os.path.split(os.path.abspath(ktest_folder))[0]+'/'+os.path.split(os.path.abspath(ktest_folder))[1]+'.assertion', 'w+')
                assertion_code_file.write(memcpy_stmt)
                assertion_code_file.write(buffer_decl_stmt)
                assertion_code_file.write(comparison_stmt)
                assertion_code_file.close()
                ### MAJOR CHANGE: Switching off automatic instrumentation for now ###
                '''
                locations_to_insert = get_location_to_insert(ktest_folder)
                modify_unit_files(locations_to_insert, (memcpy_stmt, buffer_decltarget_info = get_target_, comparison_stmt))
                '''

