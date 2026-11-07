#!/usr/bin/env python3
# Copyright (c) 2018-2019 AT&T Intellectual Property. All rights reserved.
#
# SPDX-License-Identifier: GPL-2.0-only

from parser import VyattaJSONParser, TEXT_LEAF_LABEL, OrderedDict, DIR_TRAVERSE_UP_LABEL, DICT_ELEM_LABEL, main
import unittest
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import mock_open, patch


class ParserTestCase(unittest.TestCase):
    def test_isis_hello_interval_uses_frr107_level_order(self):
        configs = Path(__file__).parent / 'configs'
        parser = VyattaJSONParser()
        parser.tree = parser.decode_vyatta_config(json.dumps({'interfaces': [
            {'tagnode': 'dp0p8s0', 'isis': {'hello-interval': {'level-1': 1, 'level-2': 2}}}]}))
        parser.discover_syntax(str(configs / 'commands'))
        parser.load_steps(str(configs / 'steps.json'))
        parser.execute_steps()
        self.assertIn('isis hello-interval level-1 1', parser.output)
        self.assertIn('isis hello-interval level-2 2', parser.output)

    def test_validation_preserves_existing_configuration(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'frr.conf'
            target.write_text('previous configuration')
            parser = VyattaJSONParser()
            parser.output = ['new configuration']
            with patch('parser.shutil.chown'):
                parser.output_config(str(target), 'routing', check_only=True)
            self.assertEqual(target.read_text(), 'previous configuration')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_validation_rejects_mount_target_and_cleans_temporary_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'frr.conf'
            target.write_text('previous configuration')
            mount = f'1 2 0:1 / {target} rw - overlay overlay rw\n'
            with patch('parser.shutil.chown'), patch('parser.open', mock_open(read_data=mount)):
                with self.assertRaises(OSError):
                    VyattaJSONParser().output_config(str(target), 'routing', check_only=True)
            self.assertEqual(target.read_text(), 'previous configuration')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_check_validates_syntax_without_reload_or_replacement(self):
        for status in [0, 2]:
            with self.subTest(status=status), TemporaryDirectory() as directory:
                source = Path(directory) / 'candidate.json'
                source.write_text('{}')
                target = Path(directory) / 'frr.conf'
                target.write_text('previous configuration')
                argv = ['parser.py', '--check', '-i', str(source), '-o', str(target),
                        '-c', str(Path(__file__).parent / 'configs')]
                with patch('parser.sys.argv', argv), patch('parser.shutil.chown'), \
                     patch('parser.subprocess.run', return_value=subprocess.CompletedProcess([], status)) as command:
                    if status:
                        with self.assertRaises(SystemExit) as result:
                            main()
                        self.assertEqual(result.exception.code, status)
                    else:
                        main()
                    command.assert_called_once()
                    self.assertEqual(command.call_args.args[0],
                                     ['/usr/bin/vtysh', '-C', '-f', '/dev/stdin'])
                self.assertEqual(target.read_text(), 'previous configuration')
                self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                                 ['candidate.json', 'frr.conf'])

    def test_ospfv3_area_uses_frr107_interface_context(self):
        configs = Path(__file__).parent / 'configs'
        parser = VyattaJSONParser()
        parser.tree = parser.decode_vyatta_config(json.dumps({
            'protocols': {'ospfv3': {'router-id': '192.0.2.1',
                'area': [{'tagnode': '0.0.0.0', 'interface': [
                    {'tagnode': 'dp0p8s0'}, {'tagnode': 'dp0p9s0'}]}]}}}))
        parser.discover_syntax(str(configs / 'commands'))
        parser.load_steps(str(configs / 'steps.json'))
        parser.execute_steps()
        text = '\n'.join(parser.output)
        for name in ['dp0p8s0', 'dp0p9s0']:
            self.assertIn('exit\ninterface ' + name + '\nipv6 ospf6 area 0.0.0.0\nexit\nrouter ospf6', text)
            self.assertNotIn('interface ' + name + ' area', text)

    def test_virtual_link_md5_key_in_default_and_vrf(self):
        ospf = {'area': [{'tagnode': '0.0.0.1', 'virtual-link': [
            {'tagnode': '2.2.2.2', 'authentication': {'md5': None,
             'md5-key-id': [{'tagnode': 1, 'md5-key': 'lab-key'}]}}]}]}
        fixtures = [
            {'protocols': {'ospf': ospf}},
            {'routing': {'routing-instance': [{'instance-name': '77',
                'protocols': {'ospf': ospf}}]}}]
        configs = Path(__file__).parent / 'configs'
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                parser = VyattaJSONParser()
                parser.tree = parser.decode_vyatta_config(json.dumps(fixture))
                parser.discover_syntax(str(configs / 'commands'))
                parser.load_steps(str(configs / 'steps.json'))
                parser.execute_steps()
                self.assertIn('area 0.0.0.1 virtual-link 2.2.2.2 '
                              'message-digest-key 1 md5 lab-key', parser.output)

    def test_config_disk_error_keeps_previous_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'frr.conf'
            target.write_text('previous configuration')
            parser = VyattaJSONParser()
            parser.output = ['new configuration']
            with patch('parser.os.fsync', side_effect=OSError(28, 'No space left')):
                with self.assertRaises(OSError):
                    parser.output_config(str(target), 'routing')
            self.assertEqual(target.read_text(), 'previous configuration')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_failed_config_owner_keeps_previous_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'frr.conf'
            target.write_text('previous configuration')
            target.chmod(0o640)
            parser = VyattaJSONParser()
            parser.output = ['ip route 192.0.2.0/24 192.0.2.1']
            with patch('parser.shutil.chown', side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    parser.output_config(str(target), 'routing')
            self.assertEqual(target.read_text(), 'previous configuration')
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_config_replace_is_private_and_repeatable(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'frr.conf'
            parser = VyattaJSONParser()
            parser.output = ['log syslog']
            with patch('parser.shutil.chown'):
                parser.output_config(str(target), 'routing')
                parser.output_config(str(target), 'routing')
            self.assertEqual(target.read_text(), 'log syslog\n!')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(parser.output, ['log syslog'])

    def test_load_all_syntax_files(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / 'one.json').write_text('{"/one": "one"}')
            (Path(directory) / 'two.json').write_text('{"/two": "two"}')
            parser = VyattaJSONParser()
            parser.read_syntax_files(directory)
            self.assertEqual(parser.syntax, {'/one': 'one', '/two': 'two'})

    def test_find_parent_dict(self):
        l0 = {}
        l1 = {}
        l2 = {}
        l31 = [1, 2, 3]
        l32 = {'area': 0}
        l2['l'] = l31
        l2['area'] = l32
        l1['ospf'] = l2
        l0['protocols'] = l1
        v = VyattaJSONParser(l0, {})
        for node, path in v.depth_first_traverse(l0):
            if len(v.parent_stack) > 0:
                if isinstance(v.parent_stack[-1], list):
                    self.assertTrue(node in v.parent_stack[-1])
                else:
                    self.assertTrue(
                        node is v.parent_stack[-1][path.split('/')[-1]])

    def test_null_decode_as_None(self):
        v = VyattaJSONParser({}, {})
        node = '{"protocols": null}'
        actual = v.decode_vyatta_config(node)['protocols']
        expected = None
        self.assertEqual(actual, expected)

    def test_obj_decode_as_OrderedDict(self):
        v = VyattaJSONParser({}, {})
        node = '{"protocols": null}'
        actual = type(v.decode_vyatta_config(node))
        expected = type(OrderedDict())
        self.assertEqual(actual, expected)

    def test_retreive_multi_OrderedDict(self):
        v = VyattaJSONParser({}, {})
        node = OrderedDict(
            [('protocols', OrderedDict([('ospf', OrderedDict([('timers', 'timerVal')]))]))])
        steps = ['protocols', DICT_ELEM_LABEL]
        actual = v.retrieve_value(node, steps)
        print(actual)
        expected = "{'ospf':{'timers':'timerVal'}}"
        self.assertEqual(actual, expected)

    def test_retreive_multi_OrderedDict_from_list(self):
        v = VyattaJSONParser({}, {})
        node = OrderedDict(
            [('protocols', [OrderedDict([('ospf', OrderedDict([('timers', 'timerVal')]))])])])
        steps = ['protocols', DICT_ELEM_LABEL]
        actual = v.retrieve_value(node, steps)
        print(actual)
        expected = "[{'ospf':{'timers':'timerVal'}}]"
        self.assertEqual(actual, expected)

    def test_retrieve_value_traverse_down(self):
        v = VyattaJSONParser({}, {})
        node = {'protocols': {'ospf': {'timers': "timerVal"}}}
        steps = ['protocols', 'ospf', 'timers', TEXT_LEAF_LABEL]
        actual = v.retrieve_value(node, steps)
        expected = "timerVal"
        self.assertEqual(actual, expected)

    def test_retrieve_value_traverse_up_simple(self):
        v = VyattaJSONParser({}, {})
        l3 = {'timers': "timerVal"}
        l2 = {'ospf': l3}
        node = {'protocols': l2, 'key': 'value'}
        v.parent_stack = [node, l2]
        steps = [DIR_TRAVERSE_UP_LABEL,
                 DIR_TRAVERSE_UP_LABEL, 'key', TEXT_LEAF_LABEL]
        actual = v.retrieve_value(l3, steps)
        expected = "value"
        self.assertEqual(actual, expected)

    def test_retrieve_value_traverse_up_mixed(self):
        v = VyattaJSONParser({}, {})
        l4 = {'timers': "timerVal"}
        l3 = [l4]
        l2 = {'ospf': l3}
        l1 = [l2]
        node = {'protocols': l1, 'key': 'value'}
        v.parent_stack = [node, l1, l2, l3]
        steps = [DIR_TRAVERSE_UP_LABEL, DIR_TRAVERSE_UP_LABEL, DIR_TRAVERSE_UP_LABEL,
                 DIR_TRAVERSE_UP_LABEL, 'key', TEXT_LEAF_LABEL]
        actual = v.retrieve_value(l4, steps)
        expected = "value"
        self.assertEqual(actual, expected)

    def test_retrieve_command_as_list(self):
        template = "{/timers/@text} {/@text}"
        path = '/protocols/ospf/freq'
        syntax = {path: template}
        v = VyattaJSONParser({}, syntax)
        actual = list(v.retrieve_commands(path))
        expected = [template]
        self.assertEqual(actual, expected)

    def test_retrieve_command_escape_dots(self):
        template = "{/../timers/@text}"
        path = '/protocols/ospf/freq'
        syntax = {path: template}
        v = VyattaJSONParser({}, syntax)
        actual = list(v.retrieve_commands(path))
        expected = ["{{/{}/timers/@text}}".format(DIR_TRAVERSE_UP_LABEL)]
        self.assertEqual(actual, expected)

    def test_traversal_up_primitive_same_value_children(self):
        l1 = {'keyN': "21", 'ospf': {'timers': "timerVal", "freq": "21"}}
        node = {'keyN': "21", 'protocols': l1, }
        syntax = {'/protocols/ospf/freq': "{/../timers/@text} {/@text}"}
        expected = ['timerVal 21']
        v = VyattaJSONParser(node, syntax)
        actual = v.parse_config()
        self.assertEqual(actual, expected)

    def test_traversal(self):
        l1 = [{'ospf': [{'timers': "timerVal", "freq": "21"}], 'keyl2': 'vall21'},
              {'keyl2': 'vall22'}]
        node = {'protocols': l1, 'key': 'value'}
        syntax = {
            '/protocols': "constant command",
            '/protocols/@element/ospf/@element':
            "timers {/timers/@text} [optional {/../../keyl2/@text},]",
            '/protocols/@element/ospf/@element/timers':
            "{/../../../../../key/@text} [nonexistant optional {/../../../../../abc/@text},]",
            '/protocols/@element/ospf/@element/freq': "{/../timers/@text} {/@text}",
            '/protocols/@element/keyl2': "Level 2 {/@text}"
        }
        expected = ['constant command', 'timers timerVal optional vall21', 'value ',
                    'timerVal 21', 'Level 2 vall21', 'Level 2 vall22']
        v = VyattaJSONParser(node, syntax)
        actual = v.parse_config()
        self.assertEqual(actual, expected)

    def test_enter_exit_commands(self):
        node = {'protocols': [{'ospf': [1, 2, 3]}], 'key': 'value'}
        syntax = {
            '/protocols/@enter': "in",
            '/protocols/@element/ospf/@element': "{/@text}",
            '/protocols/@element/ospf/@element/@enter': "i",
            '/protocols/@element/ospf/@element/@exit': "o",
            '/protocols/@exit': "out",
        }
        expected = ['in', 'i', '1', 'o', 'i', '2', 'o', 'i', '3', 'o', 'out']
        v = VyattaJSONParser(node, syntax)
        actual = v.parse_config()
        self.assertEqual(actual, expected)

    def test_priority_sorting(self):
        node = OrderedDict({'ospf': OrderedDict(
            {'timers': "timerVal", "freq": "21"})})
        syntax = {'/ospf/freq': "{/@text}", '/ospf/timers': "{/@text}"}
        first = []
        # test timers moved at the end
        last = ['timers']
        priorities = {'/ospf': {"first": first, "last": last}}
        expected = ['21', 'timerVal']
        v = VyattaJSONParser(node, syntax)
        v.sort_tree(priorities)
        actual = v.parse_config()
        self.assertEqual(actual, expected)
        # test timers moved at the front
        expected = ['timerVal', '21']
        first.append(last.pop())
        v.sort_tree(priorities)
        actual = v.parse_config()
        self.assertEqual(actual, expected)

    def test_priority_sorting_multiple_nonexisting(self):
        node = OrderedDict(
            {'key1': "1", 'key2': '2', 'key3': '3', 'key4': '4'})
        syntax = {'/key1': "{/@text}", '/key2': "{/@text}", '/key3': "{/@text}",
                  '/key4': "{/@text}"}
        first = ['key1', 'key2', 'keyN']
        last = ['key3', 'key4']
        priorities = {'/': {"first": first, "last": last}}
        v = VyattaJSONParser(node, syntax)
        v.sort_tree(priorities)
        expected = ['1', '2', '3', '4']
        actual = v.parse_config()
        self.assertEqual(actual, expected)
        # test timers moved at the front
        first.clear()
        last.clear()
        first.extend(['key4', 'key1', 'keyZ'])
        last.extend(['key3', 'key2'])
        v.sort_tree(priorities)
        expected = ['4', '1', '3', '2']
        actual = v.parse_config()
        self.assertEqual(actual, expected)

    def test_multiple_commands(self):
        l1 = [{'ospf': [{'timers': "timerVal", "freq": "21"}], 'keyl2': 'vall21'},
              {'keyl2': 'vall22'}]
        node = {'protocols': l1, 'key': 'value'}
        syntax = {
            '/protocols': ["constant command1", "constant command2"],
            '/protocols/@element/ospf/@element':
            ["Level 2 {/../../keyl2/@text}",
             "timers {/timers/@text} [optional {/../../keyl2/@text},]"],
            '/protocols/@element/ospf/@element/timers':
            ["{/../../../../../key/@text} [nonexistant optional {/../../../../../abc/@text},]",
             "{@text} {/../freq/@text}"]
        }
        expected = ["constant command1", "constant command2", 'Level 2 vall21',
                    'timers timerVal optional vall21', 'value ', 'timerVal 21']
        v = VyattaJSONParser(node, syntax)
        actual = v.parse_config()
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
