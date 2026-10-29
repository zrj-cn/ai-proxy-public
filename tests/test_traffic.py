import curses
import pathlib
import sys
import threading
import time
import unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy.traffic import TrafficModel,Sampler,channel,safe_host,human
from ai_proxy.traffic_ui import monitor,paint
import test_tui


def conn(cid='1',host='api.anthropic.com',chains=None,up=100,down=1000):
    return {'id':cid,'metadata':{'host':host,'network':'tcp','sourceIP':'private-client','inboundUser':'secret-user'},'chains':chains or ['EXIT_B'],'upload':up,'download':down,'rule':'DomainSuffix'}
def snap(items,total_up=100,total_down=1000):return {'connections':items,'uploadTotal':total_up,'downloadTotal':total_down}


class TrafficTests(unittest.TestCase):
    def test_route_uses_actual_outbound_even_if_fallback_policy(self):
        self.assertEqual(channel(['EXIT_B','CHAIN_OR_DIRECT']),'CHAIN')
        self.assertEqual(channel(['DIRECT','CHAIN_OR_DIRECT']),'FALLBACK_DIRECT')
        self.assertEqual(channel(['DIRECT']),'DIRECT')
        self.assertEqual(channel([]),'UNKNOWN')
    def test_baseline_delta_and_same_service_separate_routes(self):
        m=TrafficModel();m.update(snap([conn()]),10)
        self.assertEqual(m.route_summary('CHAIN')['down'],0)
        m.update(snap([conn(up=120,down=1200),conn('2','claude.ai',['DIRECT'],10,50)],130,1250),12)
        self.assertEqual(m.route_summary('CHAIN')['down'],200)
        self.assertEqual(m.route_summary('CHAIN')['down_rate'],100)
        self.assertEqual(m.route_summary('DIRECT')['down'],50)
        self.assertEqual(len(m.view()),2)
        self.assertEqual({r['target'] for r in m.view()},{'Claude'})
        self.assertEqual(m.rate,(15,125))
        self.assertNotIn('secret-user',repr(m.rows));self.assertNotIn('private-client',repr(m.rows))
    def test_recent_ended_no_phantom_rate_or_repeated_bytes(self):
        m=TrafficModel();m.update(snap([]),1);m.update(snap([conn()]),2)
        m.update(snap([],100,1000),3)
        row=m.view()[0];self.assertEqual(row['active'],0);self.assertEqual(row['down_rate'],0)
        self.assertEqual(m.route_summary('CHAIN')['down'],1000)
        m.update(snap([],100,1000),40);self.assertEqual(m.view(),[])
        self.assertEqual(m.route_summary('CHAIN')['down'],1000)
    def test_reset_does_not_make_negative_or_huge_rates(self):
        m=TrafficModel();m.update(snap([conn()]),1);m.update(snap([conn(down=1100)],120,1100),2)
        m.update(snap([conn(down=5)],1,5),3)
        self.assertEqual(m.rate,(None,None));self.assertEqual(m.route_summary('CHAIN')['down'],0)
        self.assertIn('重置',m.notice)
    def test_route_history_has_real_samples_unknown_gaps_and_reset(self):
        m=TrafficModel();m.update(snap([conn()]),1)
        self.assertFalse(m.route_history['CHAIN'])
        m.update(snap([conn(down=1200)],100,1200),3)
        self.assertEqual(m.route_history['CHAIN'][-1],(0,100))
        m.fail();self.assertEqual(m.route_history['CHAIN'][-1],(None,None))
        m.update(snap([],0,0),4);self.assertFalse(m.route_history['CHAIN'])

    def test_transit_endpoint_hidden_but_real_final_target_remains(self):
        m=TrafficModel(['203.0.113.7','gateway.example']);m.update(snap([conn('1','203.0.113.7'),conn('2','gateway.example'),conn('3')]),1)
        self.assertEqual(len(m.view()),1);self.assertEqual(m.view()[0]['target'],'Claude')
    def test_real_inner_tracker_excluded_without_dns_or_address_guessing(self):
        inner=conn('inner','203.0.113.44',['ENTRY_A']);inner['metadata']['type']='Inner'
        m=TrafficModel();m.update(snap([inner,conn()]),1)
        self.assertEqual([r['target'] for r in m.view()],['Claude'])
        self.assertEqual(m.active,1)

    def test_failed_poll_retains_explicitly_stale_data(self):
        m=TrafficModel();m.update(snap([conn()]),1);m.fail()
        self.assertEqual(m.rate,(None,None));self.assertEqual(len(m.view()),1);self.assertTrue(m.error)
        m.update(snap([],100,1000),3);self.assertFalse(m.error)
    def test_filters_and_malformed_data(self):
        m=TrafficModel();m.update(snap([conn(),conn('2','raw.githubusercontent.com',['DIRECT']),conn('3','unknown.example',['REJECT']),None]),1)
        self.assertEqual([r['target'] for r in m.view(2)],['GitHub'])
        self.assertEqual([r['channel'] for r in m.view(4)],['REJECT'])
        self.assertEqual(len(m.view(query='anthropic')),1)
        m.update({'connections':'bad'});self.assertTrue(m.error)
    def test_sanitization_and_bound(self):
        self.assertEqual(safe_host('https://user:password@claude.ai/path?token=secret'),'claude.ai')
        self.assertNotIn('\x1b',safe_host('\x1b[31mclaude.ai'))
        m=TrafficModel(limit=3);m.update(snap([conn(str(i),f'{i}.example') for i in range(10)]),1)
        self.assertEqual(len(m.rows),3);self.assertTrue(m.evicted)
        self.assertEqual(human(None,True),'—')
    def test_sampler_errors_redacted_and_close_responsive(self):
        called=threading.Event();release=threading.Event()
        def fetch():called.set();release.wait(2);raise RuntimeError('password-do-not-render')
        s=Sampler(fetch,interval=.01).start();self.assertTrue(called.wait(1))
        before=time.monotonic();s.close();self.assertLess(time.monotonic()-before,.4)
        release.set();s.thread.join(1)
        self.assertIsNone(s.latest())
        with mock.patch.object(s,'fetch',side_effect=RuntimeError('secret')):
            s=Sampler(s.fetch,interval=.01).start()
            try:
                end=time.monotonic()+1;event=None
                while event is None and time.monotonic()<end:event=s.latest();time.sleep(.01)
                self.assertIsNotNone(event);self.assertNotIn('secret',str(event))
            finally:s.close()


class TrafficNavigation(unittest.TestCase):
    setUp=test_tui.Navigation.setUp
    def ui(self,keys):
        ui=test_tui.Navigation.ui(self,keys)
        ui.screen.getmaxyx=lambda:(28,120)
        return ui
    def test_monitor_keyboard_routes_pause_details_and_cleanup(self):
        ui=self.ui([' ',curses.KEY_RIGHT,curses.KEY_LEFT,'\r','\r','f','s','\x1b'])
        m=TrafficModel();m.update(snap([conn()]),1)
        sampler=mock.Mock();sampler.latest.return_value=None
        monitor(ui,sampler,m)
        output=' '.join(ui.screen.output)
        self.assertIn('暂停画面',output);self.assertIn('连接详情',output)
        sampler.close.assert_called_once()
    def test_monitor_ctrl_c_closes_sampler(self):
        ui=self.ui(['\x03']);sampler=mock.Mock();sampler.latest.return_value=None
        with self.assertRaises(KeyboardInterrupt):monitor(ui,sampler,TrafficModel())
        sampler.close.assert_called_once()
    def test_three_views_and_palette_fallback(self):
        from ai_proxy.dashboard import Theme,digits
        ui=self.ui([]);ui.screen.getmaxyx=lambda:(48,160)
        m=TrafficModel();m.update(snap([conn()]),1);m.update(snap([conn(down=2200)],100,2200),2)
        for view in ['overview','targets','timeline']:
            paint(ui,m,m.view(),0,0,False,'speed',False,'',3,view=view)
        out=' '.join(ui.screen.output)
        self.assertIn('ACTIVITY',out);self.assertIn('TARGET VELOCITY',out);self.assertIn('█',out)
        self.assertEqual(len(digits('12.5')),5)
        with mock.patch.dict('os.environ',{'NO_COLOR':'1'}),mock.patch.object(curses,'init_pair') as init:
            self.assertEqual(Theme()('mint'),0);init.assert_not_called()
        with mock.patch.dict('os.environ',{'NO_COLOR':''}),mock.patch.object(curses,'has_colors',return_value=True),mock.patch.object(curses,'start_color'),mock.patch.object(curses,'COLORS',256,create=True),mock.patch.object(curses,'COLOR_PAIRS',256,create=True),mock.patch.object(curses,'init_pair'),mock.patch.object(curses,'color_pair',side_effect=lambda n:n):
            self.assertNotEqual(Theme()('mint'),Theme()('gold'))
    def test_tab_and_number_shortcuts_do_not_change_routes(self):
        ui=self.ui(['\t','\t',curses.KEY_F1,'2',curses.KEY_LEFT,'\x1b'])
        sampler=mock.Mock();sampler.latest.return_value=None
        with mock.patch('ai_proxy.traffic_ui.paint',return_value=3) as draw:
            monitor(ui,sampler,TrafficModel())
        self.assertEqual({call.args[-1] for call in draw.call_args_list},{'overview','targets','timeline'})
        sampler.close.assert_called_once()

    def test_wide_and_small_render(self):
        ui=self.ui([]);m=TrafficModel();m.update(snap([conn()]),1)
        ui.screen.getmaxyx=lambda:(32,140)
        paint(ui,m,m.view(),0,0,False,'speed',False,'',2)
        self.assertIn('Claude',' '.join(ui.screen.output))
        self.assertIn('入口 A 与落地 B',' '.join(ui.screen.output))
        ui.screen.getmaxyx=lambda:(10,40)
        paint(ui,m,[],0,0,False,'speed',False,'',2)
        self.assertIn('至少 60',' '.join(ui.screen.output))
