#-*- coding: utf-8 -*-

import boto3

import imp
import subprocess

from hst.hst import main
import os
import sys
if os.name != 'posix':
    sys.exit('platform not supported')
import logging
import os
import argparse
from hst.hst import Picker, QuitException
from functools import partial

import locale
locale.setlocale(locale.LC_ALL,"")

logger = logging.getLogger(__name__)
import curses

from .client import AWSCli


SEPARATOR = '|'


class SimpleLineLoader(object):
    def __init__(self, client, region=None, tags=None):
        self.client = client
        self.region = region
        self.tags = tags

    def load(self):
        instances = self.client.get_instances(self.region, self.tags)
        lines = []
        for i in instances:
            name = [tag['Value'] for tag in i.tags if tag['Key'] == 'Name'][0]
            line = []
            ip = i.public_ip_address or i.private_ip_address
            line.append(name.ljust(50))
            line.append(' | ')
            line.append(ip.ljust(16))
            line.append(' | ')
            line.append('{}'.format(i.key_name).ljust(30))
            line.append(' | ')
            line.append('{}'.format(i.id))
            lines.append(' '.join(line))

        return lines

class AsshPicker(Picker):

    client = None
    output_only = False

    def get_data_from_line(self, line):
        instance_id = line.split(SEPARATOR)[-1].strip()
        instance = self.client.get_instance(instance_id)
        ip = instance.public_ip_address or instance.private_ip_address
        nat_ip, nat_key = self.client.get_nat(instance)
        return {'ip': ip,
                'instance_id': instance_id,
                'nat_ip': nat_ip,
                'nat_key': nat_key,
                'key_name': instance.key_name,
                'tags': instance.tags}



    def get_hostname_from_line(self, line):
        return line.split(SEPARATOR)[0].strip()

    def get_instance_id_from_line(self, line):
        return line.split(SEPARATOR)[1].strip()

    def get_cmd_fn_from_modules(self, *modules):
        for module in modules:
            fn = getattr(module, 'cmd_{}'.format(self.args.command.upper()), None)
            if fn:
                return fn

    def get_ispublic(self, line):
        return line.split(SEPARATOR)[2].strip() != 'None'

    def get_cmd_fn(self, cmd_name):
        from . import commands
        fn = self.get_cmd_fn_from_modules(self.settings, commands)
        if fn:
            return partial(fn, self)

        # look for builtins
        return getattr(self, 'cmd_{}'.format(self.args.command.upper()))

    def write_output(self, line):
        with open(self.args.out, 'w') as f:
            if self.output_only:
                out = '''cat <<'HereDocFromASSH' \n %s \nHereDocFromASSH\n\n''' % line
                f.write(out.encode('utf8'))
            else:
                f.write(line.encode('utf8'))

    def show_output(self, t):
        self.output_only = t

    def create_menu(self):
        self.win.addstr(3, 10, "xxxxxxxxxxx", curses.color_pair(1))
        for i in range(0, 10):
            self.win.addstr(4 + i, 10, "x    {}     x".format(i), curses.color_pair(1))
        self.win.addstr(4 + 10, 10, "xxxxxxxxxxx", curses.color_pair(1))

    def refresh_window(self, pressed_key=None):
        self.lineno = 0
        if pressed_key:
            self.search_txt = self.append_after_cursor(self.search_txt, pressed_key)

        # curses.endwin()
        self.win.erase()

        self.print_header(self.search_txt, cursor=True)

        logger.debug("======================== refresh window ======================")
        self.which_lines(self.search_txt)

        if not self.last_lines:
            self.print_line("Results [{}]".format(self.index.size()), highlight=True)
        else:
            self.print_line("Results - [{}]".format(len(self.last_lines)), highlight=True)

        max_y, max_x = self.get_max_viewport()

        if self.selected_lineno > len(self.which_lines(self.search_txt)) - 1:
            self.selected_lineno = len(self.which_lines(self.search_txt)) - 1

        logger.debug("self.multiple selected %s", self.multiple_selected)

        for i, p in enumerate(self.last_lines[0:max_y]):
            selected = i == self.selected_lineno
            pending = (self.pick_line(i) in self.multiple_selected)
            logger.debug("is pending %s [%s____%s]", pending, self.pick_line(i), self.multiple_selected)
            try:
                if pending:
                    line = u"[x] {}".format(p[1])
                else:
                    line = u"[ ] {}".format(p[1])
            except:
                logger.exception("exception in adding line %s", p)
            else:
                try:
                    self.print_line(line.strip(), highlight=selected, semi_highlight=pending)
                except curses.error:
                    break

        # self.create_menu()

        try:
            s = 'type something to search | [F5] copy | [TAB] complete to current | [ENTER] run | [ESC] quit'
            self.print_footer("[%s] %s" % (self.mode, s))
        except curses.error as e:
            pass
        self.win.refresh()

    def key_ENTER(self):
        # if not self.args.command:
        #     self.create_menu()
        #     self.refresh_window()
        #     return
        line = self.pick_line()
        self.no_enter_yet = False
        logger.debug("selected_lineno: %s", line)

        args = self.get_data_from_line(line)

        logger.debug("selected line: %s", line)

#        if self.args.eval
#            if self.args.replace:
#                line = self.args.eval.replace(self.args.replace, line)
#            else:
#                line = "%s %s" % (self.args.eval, line)

        if self.args.rest:
            for arg in self.args.rest:
                key, value = arg.split('=')
                args[key] = value


        if self.args.command:
            fn = self.get_cmd_fn(self.args.command)
            line = fn(**args)

        self.write_output(line)

        raise QuitException()

    def key_DOWN(self):
        max_y, max_x = self.get_max_viewport()

        if self.selected_lineno < max_y - 1:
            self.selected_lineno += 1

        self.refresh_window()

    def get_instance_by_public_ip(self, public_ip):
        for i in self.loader.instances:
            if i.public_dns_name == public_ip:
                return i


def assh():
    parser = argparse.ArgumentParser()

    parser.add_argument("-o", "--out", type=str,
                    help="output to file")

    parser.add_argument("-F", "--filter-tag",
                        nargs='+',
                    help="filter by tags eg: --filter-tag=Name:app1")

    parser.add_argument('-N', '--filter-name', help="filter by tag Name")

    parser.add_argument("-d", "--debug",
                    help="debug mode - shows scores etc.")

    parser.add_argument("-i", "--input",
                    help="input file")

    parser.add_argument("-e", "--eval",
                    help="evaluate command output")

    parser.add_argument("-p", "--pipe-out", action='store_true',
                    help="just echo the selected command, useful for pipe out")

    parser.add_argument("-I", "--separator",
                        default=',',
                        help="seperator in for multiple selection - ie. to join selected lines with ; etc.")

    parser.add_argument("-r", "--replace",
                        default=' ',
                        help="replace with this in eval string. ie. hst -r '__' --eval='cd __ && ls'")

    parser.add_argument("-l", "--logfile",
                        default='assh.log',
                        help="where to put log file in debug mode")

    parser.add_argument("account", type=str,
                    help="aws account")
    #
    parser.add_argument("command", type=str, nargs='?',
                    help="command - eg. ssh, fab")

    parser.add_argument('rest', nargs=argparse.REMAINDER)


    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        hdlr = logging.FileHandler(args.logfile)
        logger.addHandler(hdlr)
    else:
        logger.setLevel(logging.CRITICAL)

    settings = imp.load_source('settings', '%s/.assh/%s.py' % (os.path.expanduser('~'), args.account))

    AsshPicker.settings = settings

    tags = {}
    if args.filter_tag:
        for n in args.filter_tag:
            k, v = n.split(':')
            tags[k] = v

    if args.filter_name:
        tags['Name'] = args.filter_name
    
    client = AWSCli(settings.AWS_REGION,
                    settings.AWS_ACCESS_KEY_ID,
                    settings.AWS_SECRET_ACCESS_KEY,
                    settings.AWS_SECURITY_TOKEN)
  
    AsshPicker.client = client


    loader = SimpleLineLoader(client=client,
                              tags=tags)

    lines = loader.load()

    if args.command=='list':
        for n in lines:
            print(n)
        return

    #if len(lines) == 1:
    #    # no need to select anything...
    #    picker = AsshPicker(args=args)
    #    fn = picker.get_cmd_fn(args.command)
    #    line = fn(lines[0].split(SEPARATOR)[0].strip())
    #    picker.write_output(line)
    #    return

    main(args,
         picker_cls=AsshPicker,
         loader=loader)

if __name__ == '__main__':
    assh()
