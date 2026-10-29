import copy, json, pathlib, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import core as c
from ai_proxy.main import node_import, parse_bytes, rule_cmd

class Routing(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=pathlib.Path(self.tmp.name)
        self.patches=[mock.patch.object(c,k,p/v) for k,v in [('C','config'),('D','data'),('S','state')]]
        for patch in self.patches:patch.start();self.addCleanup(patch.stop)
        c.init()
    def test_ai_wins_and_default_closed(self):
        for h in ['api.openai.com','auth.openai.com','chatgpt.com','api.anthropic.com','mcp-proxy.anthropic.com','bridge.claudeusercontent.com','widget.claudemcpcontent.com','new-ai.example']:
            self.assertEqual(c.explain(h)['action'],'CHAIN')
        cfg=c.generate();self.assertFalse(cfg['proxies']);self.assertEqual(cfg['rules'][-1],'MATCH,REJECT')
    def test_download_and_shared_domains(self):
        for h in ['raw.githubusercontent.com','release-assets.githubusercontent.com','objects.githubusercontent.com','cas-bridge.xethub.hf.co','transfer.xethub.hf.co','cdn-lfs-us-1.hf.co','pypi.org','files.pythonhosted.org','pypi.python.org','bootstrap.pypa.io','download.pytorch.org','download-r2.pytorch.org','developer.download.nvidia.com','international.download.nvidia.com','pypi.nvidia.com','pypi.ngc.nvidia.com']:
            self.assertEqual(c.explain(h)['action'],'DIRECT')
        for h in ['evilgithub.com','github.com.evil.test','arbitrary.amazonaws.com','random.cloudflare.com','api.datadoghq.com','api.nvidia.com','pytorch.org','arbitrary.cloudfront.net','download.pytorch.org.evil.test','notpypi.org']:
            self.assertEqual(c.explain(h)['action'],'CHAIN')
    def test_private_ip_only_no_dns(self):
        self.assertEqual(c.explain('127.0.0.1')['action'],'DIRECT')
        self.assertEqual(c.explain('https://api.openai.com')['action'],'CHAIN')
        self.assertTrue(all(r.endswith(',no-resolve') for r in c.generate()['rules'] if r.startswith('IP-')))
    def test_subscription_cannot_inject(self):
        data={'proxies':[{'name':'x','type':'http','server':'entry.test','port':1234}], 'tun':{'enable':True},'authentication':[], 'rules':['MATCH,DIRECT']}
        imported=node_import(data)
        self.assertEqual(list(imported),['1'])
        self.assertNotIn('rules',imported)
        data['proxies'][0]['dialer-proxy']='DIRECT'
        with self.assertRaises(c.Error):node_import(data)
    def test_chain_b_contains_dialer(self):
        nodes={'a':{'type':'http','server':'a.example','port':80},'b':{'type':'socks5','server':'b.example','port':1080}}
        st=c.settings();st.update(entry='a',exit='b');cfg=c.generate(st,nodes)
        self.assertEqual(cfg['proxies'][1]['dialer-proxy'],'ENTRY_A')
        self.assertNotIn('dialer-proxy',cfg['proxies'][0])
        self.assertEqual(cfg['rules'][-1],'MATCH,EXIT_B')
        self.assertNotIn('proxy-groups',cfg)
    def test_reject_bad_protocol_and_same_hop(self):
        with self.assertRaises(c.Error):c.clean_node({'type':'hysteria2','server':'a.test','port':443})
        self.assertTrue(c.clean_node({'type':'http','server':'a.test','port':443,'skip-cert-verify':True})['skip-cert-verify'])
        n={'a':{'type':'http','server':'a.test','port':443}};st=c.settings();st.update(entry='a',exit='a')
        with self.assertRaises(c.Error):c.generate(st,n)
    def test_transaction_restores_input_on_failure(self):
        old=c.snapshot()
        def change():c.save(c.C/'nodes.json',{'bad':'secret'})
        with mock.patch.object(c,'apply',side_effect=c.Error('reject')):
            with self.assertRaises(c.Error):c.transaction(change)
        self.assertEqual(c.snapshot(),old)
    def test_ai_direct_conflict_refused(self):
        with self.assertRaises(c.Error):rule_cmd(['add','DOMAIN-SUFFIX','com','DIRECT'])
        self.assertEqual(c.read(c.C/'custom-rules.json'),[])
    def test_permissions(self):
        self.assertEqual(c.C.stat().st_mode&0o777,0o700)
        for f in c.C.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600)
    def test_redaction(self):
        cred=c.read(c.C/'credentials.json')
        s=c.redact('http://user:secret@example/?token=x '+cred['api_secret']+' '+cred['password'])
        self.assertNotIn('example',s);self.assertNotIn(cred['api_secret'],s);self.assertNotIn(cred['password'],s)
    def test_uri_subscription_preserves_explicit_tls_exception(self):
        from ai_proxy.subscription import decode
        import base64
        raw=base64.b64encode(b'trojan://test-only@entry.example:443?allowInsecure=1&sni=entry.example#HK-test')
        d=decode(raw)
        self.assertTrue(d['proxies'][0]['skip-cert-verify'])
        self.assertEqual(d['_insecure_tls_count'],1)
        self.assertEqual(d['proxies'][0]['password'],'test-only')

    def test_fallback_opt_in_does_not_change_ai_or_default(self):
        c.save(c.C/'custom-rules.json',[{'type':'DOMAIN','value':'ordinary.example','action':'FALLBACK','source':'custom'}])
        nodes={'a':{'type':'http','server':'a.example','port':80},'b':{'type':'socks5','server':'b.example','port':1080}}
        st=c.settings();st.update(entry='a',exit='b');cfg=c.generate(st,nodes)
        self.assertIn('DOMAIN,ordinary.example,CHAIN_OR_DIRECT',cfg['rules'])
        self.assertIn('DOMAIN-SUFFIX,anthropic.com,EXIT_B',cfg['rules'])
        self.assertEqual(cfg['rules'][-1],'MATCH,EXIT_B')
        self.assertEqual(cfg['proxy-groups'][0]['proxies'],['EXIT_B','DIRECT'])
        self.assertNotIn('proxy-groups',c.generate(st,nodes,forced='chain'))
    def test_edit_non_ai_rule_can_change_its_policy(self):
        c.save(c.C/'custom-rules.json',[{'type':'DOMAIN','value':'ordinary.example','action':'CHAIN','source':'custom'}])
        with mock.patch.object(c,'apply'):
            rule_cmd(['edit','1','DOMAIN','ordinary.example','FALLBACK'])
        self.assertEqual(c.read(c.C/'custom-rules.json')[0]['action'],'FALLBACK')

    def test_fallback_is_domain_only(self):
        with self.assertRaises(c.Error):c.normalize_rule({'type':'IP-CIDR','value':'0.0.0.0/0','action':'FALLBACK'})

    def test_fallback_without_nodes_stays_closed(self):
        c.save(c.C/'custom-rules.json',[{'type':'DOMAIN','value':'ordinary.example','action':'FALLBACK'}])
        cfg=c.generate();self.assertIn('DOMAIN,ordinary.example,REJECT',cfg['rules']);self.assertNotIn('proxy-groups',cfg)
    def test_fallback_cannot_cover_known_ai(self):
        for domain in ['claude.ai','clau.de','claudemcpclient.com','com']:
            c.save(c.C/'custom-rules.json',[{'type':'DOMAIN-SUFFIX','value':domain,'action':'FALLBACK'}])
            with self.assertRaises(c.Error):c.generate()
    def test_claude_related_hosts_are_explicitly_forced(self):
        for domain in ['clau.de','client.claudemcpclient.com','anthropic.auth0.com','servd-anthropic-website.b-cdn.net']:
            rule=c.explain(domain);self.assertEqual(rule['action'],'CHAIN');self.assertNotEqual(rule['type'],'MATCH')

    def test_invalid_rule_rejected(self):
        for v in ['*.openai.com','http://openai.com','x.com,DIRECT','a..com']:
            with self.assertRaises(c.Error):c.normalize_rule({'type':'DOMAIN','value':v,'action':'DIRECT'})
    def test_no_resolve_ip_conflicts(self):
        rs=[{'type':'IP-CIDR6','value':'::1/128','action':'DIRECT'},{'type':'IP-CIDR','value':'127.0.0.0/8','action':'CHAIN'}]
        self.assertEqual(c.conflicts(rs),[])

if __name__=='__main__':unittest.main()
