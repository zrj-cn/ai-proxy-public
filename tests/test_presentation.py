import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import presentation as p
from ai_proxy import main
from ai_proxy.tui import wrapped,width

class Presentation(unittest.TestCase):
    def test_doctor_summary_not_json(self):
        text=p.render([{'check':'配置合法','result':'通过','detail':''},{'check':'Claude 实际请求','result':'未验证','detail':'未安装'}])
        self.assertIn('通过 1 项',text);self.assertIn('未验证 1 项',text)
        self.assertIn('未安装',text);self.assertNotIn('"check"',text);self.assertNotIn('{',text)
    def test_chain_result_is_readable(self):
        value={'result':'通过','mode':'chain','ok':True,'exit_ip':'192.0.2.3','same_exit_as_B':True,'socket_evidence':{'proc_observation_available':True,'entry_socket_seen':True,'direct_B_socket_seen':False}}
        text=p.render(value)
        self.assertIn('最终出口 IP：192.0.2.3',text);self.assertIn('与 B 出口一致：是',text);self.assertNotIn('socket_evidence',text)
    def test_http_401_is_not_misreported_as_ai_success(self):
        text=p.render({'ok':False,'history':[{'host':'api.anthropic.com','status':401}]})
        self.assertIn('HTTP 状态非成功',text);self.assertIn('不等于 AI 应用可用',text)
        self.assertNotIn('通过',text)
    def test_unconfigured_status_does_not_claim_ready_chain(self):
        text=p.render({'service':'运行','http_proxy':'本地入口','chain':'未配置真实 A/B；REJECT'})
        self.assertIn('未配置真实 A/B',text)

    def test_json_is_explicit_and_machine_readable(self):
        value={'result':'未验证','ok':False};out=io.StringIO()
        with contextlib.redirect_stdout(out):p.emit(value,json_mode=True)
        self.assertEqual(json.loads(out.getvalue()),value)
    def test_ui_capture_is_human_even_with_json_flag(self):
        value={'priority':1,'action':'CHAIN','value':'claude.ai'};out=io.StringIO()
        with p.capture() as data,contextlib.redirect_stdout(out):p.emit(value,json_mode=True)
        self.assertEqual(data,[value]);self.assertIn('路由策略',out.getvalue());self.assertNotIn('{',out.getvalue())
    def test_details_remain_readable_and_hide_signature(self):
        text=p.render({'signature':'internal-hash','history':[{'host':'claude.ai','status':401}]},details=True)
        self.assertIn('目标域名：claude.ai',text);self.assertNotIn('internal-hash',text);self.assertNotIn('"',text)
    def test_chinese_and_long_host_wrap(self):
        rows=wrapped('通过 这是一个很长的中文结果 '+ 'a'*100+'.example',32)
        self.assertTrue(all(width(row)<=32 for row in rows));self.assertGreater(len(rows),3)
    def test_quick_commands_share_service_handler(self):
        with mock.patch.object(main.c,'settings',return_value={}),mock.patch.object(main,'service') as service:
            for cmd,action in [('on','start'),('off','stop'),('restart','restart')]:
                main.dispatch([cmd]);service.assert_called_with([action])
            with mock.patch.object(main.c,'active',return_value=True):main.dispatch(['toggle']);service.assert_called_with(['stop'])
            with mock.patch.object(main.c,'active',return_value=False):main.dispatch(['toggle']);service.assert_called_with(['start'])
