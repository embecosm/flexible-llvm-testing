#!/usr/bin/python


# This is a wrapper script to execute a test program remotely under GDB using
# the python pexpect library. This script should be provided to lnt or the
# test suite through the RUNUNDER environment variable.
#
# Hardcoded values are used for the configuration here.


import pexpect
import os
import sys


def main():
    gdb_cfg = GdbConfig()
    gdb_cfg.gdb_to_run = 'gdb'
    gdb_cfg.prog       = sys.argv[1]
    gdb_cfg.prog_args  = sys.argv[2:]

    gdb_cfg.rsp_port = '50000'
    gdb_cfg.timeout  = 15
    gdb_cfg.remote_timeout = 60
    gdb_cfg.with_remote_timeout = True

    gdb_cfg.run_cmd = 'jump *__start'
    gdb_cfg.print_return_code = 'print /u $0'


    try:
        gdb_session = GdbWrapper(gdb_cfg)
        gdb_session.add_breakpoint('exit')

        ret_code = gdb_session.run()
        os._exit(ret_code)
    except:
        os._exit(-1)


if __name__ == "__main__":
    main()


class GdbConfig:
    def __init__(self):
        self.gdb_to_run = 'gdb' # command or path to gdb to run

        # filename and argv of the executed program
        self.prog       = 'a.out'
        self.prog_args  = []

        # host ip and port for rsp communication
        self.rsp_host   = ''
        self.rsp_port   = '0'

        # timeout for gdb commands, and remote execution
        self.timeout = 15
        self.remote_timeout = 0
        self.with_remote_timeout = False

        self.run_cmd    = ''            # command to begin execution
        self.start_sym  = ''            # symbol to begin execution at
        self.print_return_code = ''     # command to print the return code


class GdbWrapper:
    def __init__(self, gdb_config):
        assert isinstance(gdb_config, GdbConfig)

        self.cfg = gdb_config

        # file to dump output to
        self.output_file = '/tmp/gdb_dump'

        gdb_cmd = self.cfg.gdb_to_run.strip() + ' ' + self.cfg.prog + ' --annotate=3'
        # append arguments for the program
        if self.cfg.prog_args:
            gdb_cmd = gdb_cmd + ' --args ' + ' '.join(self.cfg.prog_args)

        # spawn process for the gdb session
        self.child = pexpect.spawn(gdb_cmd, timeout=self.cfg.timeout)

        # disable pagination
        self.wait_for_prompt()
        self.child.sendline('set height 0')
        self.wait_for_prompt()
        self.child.sendline('set width 0')

        # use the host, port and remote target
        self.wait_for_prompt()
        host_and_port = self.cfg.rsp_host + ':' + self.cfg.rsp_port
        self.child.sendline('tar rem ' + str(host_and_port))

        self.child.expect('Remote debugging using :' + str(self.cfg.rsp_port))
        self.wait_for_prompt()

        # load in the file
        self.child.sendline('load')
        self.wait_for_prompt()


    def wait_for_prompt(self):
        return self.child.expect('\x1a\x1aprompt')


    def add_breakpoint(self, pos):
        self.child.sendline('break ' + pos)
        index = self.child.expect(['\x1a\x1aprompt', '\x1a\x1aquery'])
        if index == 1:
            self.child.sendline('y')
            self.child.expect('\x1a\x1apost-query')
            self.wait_for_prompt()


    def set_remote_timeout(self, timeout=0):
        assert isinstance(timeout, int)
        assert isinstance(self.cfg.timeout, int)

        # don't set a remote timeout if it's not supported
        if not self.cfg.with_remote_timeout:
            return

        if timeout <= 0:
            timeout = self.cfg.remote_timeout

        if timeout > 0:
            self.child.sendline('monitor timeout ' + str(self.cfg.remote_timeout))
            self.wait_for_prompt()


    def run(self, timeout=0):
        # set the timeout for this execution
        self.set_remote_timeout(timeout)


        # log all output from the executing program to a file
        self.child.sendline('set logging file ' + self.output_file)
        self.wait_for_prompt()

        self.child.sendline('set logging overwrite on')
        self.wait_for_prompt()
        
        self.child.sendline('set logging on')
        self.wait_for_prompt()
        

        # if there is a start symbol, begin execution by jumping to it
        # otherwise, use the run command
        if self.cfg.start_sym:
            self.child.sendline('jump *' + self.cfg.start_sym)
        else:
            assert self.cfg.run_cmd
            self.child.sendline(self.cfg.run_cmd)


        # wait for a breakpoint or signal, error on target signal (timeout),
        # or if the target becomes unresponsive
        run_timeout = self.cfg.timeout
        if self.cfg.remote_timeout > 0:
            run_timeout = 2 * self.cfg.remote_timeout
        elif timeout > 0:
            run_timeout = timeout

        index = self.child.expect(
                ['\x1a\x1abreakpoint', '\x1a\x1asignal', pexpect.TIMEOUT],
                timeout=run_timeout)
        if index == 1:
            raise Exception('target timeout')
        elif index == 2:
            raise Exception('target unresponsive')
        self.wait_for_prompt()


        # finish logging
        self.child.sendline('set logging off')
        self.wait_for_prompt()


        # retrieve the return code using the provided print command
        self.child.sendline(self.cfg.print_return_code)
        self.child.expect('\$\S+ = (\S+)')
        ret_code = int(self.child.match.group(1))
        self.wait_for_prompt()

        # retrieve the output from the file and dump it on stderr
        output = ''

        # extract printed output from the log file and dump to stderr
        copying = False
        with open(self.output_file) as f:
            for line in f:
                if not copying and '\x1a\x1astarting' in line:
                    copying = True
                    continue

                # stop at the next annotation
                if copying and '\x1a\x1a' in line:
                    copying = False
                    break

                if copying:
                    output = output + line

        # remove trailing newline and print to stderr
        sys.stderr.write(output[:-1])
        return ret_code
