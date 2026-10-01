"""Real signature verification with locally generated ephemeral fixture keys only."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from rumbo.workos import WorkOSConnectVerifier


@unittest.skipUnless(importlib.util.find_spec('jwt') and importlib.util.find_spec('cryptography'), 'Install requirements-authkit.txt for signature tests')
class WorkOSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid='fixture-key',use='sig',alg='RS256')

    def setUp(self):
        self.now=int(time.time())
        self.config=dict(oauth_provider='workos',issuer='https://auth.rumbo.test',public_url='https://rumbo.test/mcp',owner_resource='https://rumbo.test/owner',authorization_endpoint='https://auth.rumbo.test/oauth2/authorize',token_endpoint='https://auth.rumbo.test/oauth2/token',introspection_url='https://auth.rumbo.test/oauth2/introspection',introspection_client_id='client_mcp',introspection_secret_env='RUMBO_FIXTURE_MCP',owner_client_id='client_owner',owner_client_secret_env='RUMBO_FIXTURE_OWNER')
        self.claims=dict(iss=self.config['issuer'],aud=self.config['public_url'],client_id='client_mcp',sub='user_fixture',sid='app_consent_fixture',jti='token-fixture',scope='rumbo:read rumbo:write',iat=self.now-1,exp=self.now+300)
        self.calls=[]; self.active=True; self.introspection_patch={}; self.jwks={'keys':[copy.deepcopy(self.jwk)]}
        self.secrets=patch.dict(os.environ,RUMBO_FIXTURE_MCP='ephemeral-test-client-secret',RUMBO_FIXTURE_OWNER='ephemeral-test-owner-secret')
        self.secrets.start();self.addCleanup(self.secrets.stop)
        self.verifier=WorkOSConnectVerifier(self.config,'mcp',fetch_json=self.fetch)

    def token(self,claims=None,key=None,**headers):
        import jwt
        return jwt.encode(claims or self.claims,key or self.key,algorithm='RS256',headers=dict(kid='fixture-key',**headers))

    def fetch(self,url,method='GET',data=None,headers=None):
        self.calls.append((url,method,data,headers))
        if url.endswith('/oauth2/jwks'):return copy.deepcopy(self.jwks)
        self.assertEqual(url,self.config['introspection_url'])
        body=parse_qs(data.decode());self.assertNotIn('Authorization',headers)
        self.assertEqual(body['client_id'],['client_mcp' if self.verifier.kind=='mcp' else 'client_owner'])
        self.assertIn('client_secret',body)
        # The real WorkOS response omits scope. JWT scope must be verified separately.
        fields={k:v for k,v in self.claims.items() if k!='scope'}
        result=dict(fields,active=self.active,token_type='access_token');result.update(self.introspection_patch);return result

    def test_signed_claims_plus_active_body_introspection(self):
        result=self.verifier.verify_access(self.token())
        self.assertEqual(result['scope'],'rumbo:read rumbo:write')
        self.assertEqual(result['sub'],'user_fixture')
        self.assertEqual([c[1] for c in self.calls],['GET','POST'])

    def test_inactive_or_mismatched_introspection_never_borrows_jwt_authority(self):
        for patchdata in [dict(active=False),dict(sub='user_other'),dict(client_id='client_other'),dict(iss='https://evil.test'),dict(aud=self.config['owner_resource']),dict(exp=self.now+200),dict(jti='other'),dict(token_type='refresh_token')]:
            self.introspection_patch=patchdata
            with self.subTest(patch=patchdata),self.assertRaises(ValueError):self.verifier.verify_access(self.token())
        self.introspection_patch={}
        self.active=False
        with self.assertRaises(ValueError):self.verifier.verify_access(self.token())

    def test_bad_signature_algorithm_header_and_key_are_rejected(self):
        import jwt
        tokens=[self.token(key=self.other),jwt.encode(self.claims,'synthetic-key-at-least-thirty-two-bytes',algorithm='HS256',headers={'kid':'fixture-key'}),jwt.encode(self.claims,key=None,algorithm='none'),self.token(crit=['unknown']),self.token(jku='https://evil.test/jwks')]
        for token in tokens:
            with self.subTest(token=token[:12]),self.assertRaises(ValueError):self.verifier.verify_access(token)
        self.assertFalse(any(c[1]=='POST' for c in self.calls))

    def test_exact_audience_client_scope_subject_and_time_required(self):
        for patchdata in [dict(aud='wrong'),dict(aud=[self.config['public_url'],self.config['owner_resource']]),dict(iss='https://evil.test'),dict(client_id='client_owner'),dict(sub='client_machine'),dict(scope=''),dict(scope='rumbo:owner'),dict(scope='rumbo:read rumbo:write rumbo:owner'),dict(exp=self.now-1),dict(exp=True),dict(iat=self.now+100),dict(nbf=self.now+100),dict(exp='9999999999')]:
            claims=dict(self.claims,**patchdata)
            with self.subTest(patch=patchdata),self.assertRaises(ValueError):self.verifier.verify_access(self.token(claims))
        for field in ['scope','sub','aud','iss','client_id','exp','iat','sid','jti']:
            claims=dict(self.claims);del claims[field]
            with self.subTest(missing=field),self.assertRaises(ValueError):self.verifier.verify_access(self.token(claims))

    def test_owner_nonce_and_id_token_bind_to_same_subject_and_client(self):
        self.verifier=WorkOSConnectVerifier(self.config,'owner',fetch_json=self.fetch)
        self.claims.update(aud=self.config['owner_resource'],client_id='client_owner',scope='openid rumbo:owner')
        access=self.token()
        identity=dict(iss=self.config['issuer'],aud='client_owner',sub='user_fixture',iat=self.now-1,exp=self.now+300,nonce='browser-nonce')
        result=self.verifier.verify_owner(access,self.token(identity),'browser-nonce')
        self.assertEqual(result['scope'],'rumbo:owner')
        for patchdata in [dict(nonce='wrong'),dict(sub='user_other'),dict(aud='client_mcp'),dict(exp=self.now-2),dict(iss='https://evil.test')]:
            with self.subTest(patch=patchdata),self.assertRaises(ValueError):self.verifier.verify_owner(access,self.token(dict(identity,**patchdata)),'browser-nonce')
        with self.assertRaises(ValueError):self.verifier.verify_owner(access,None,'browser-nonce')

    def test_key_rotation_is_bounded_and_duplicate_kids_fail_closed(self):
        self.verifier.verify_access(self.token());before=len([c for c in self.calls if c[1]=='GET'])
        import jwt
        for i in range(5):
            token=jwt.encode(self.claims,self.key,algorithm='RS256',headers={'kid':'unknown-'+str(i)})
            with self.assertRaises(ValueError):self.verifier.verify_access(token)
        self.assertLessEqual(len([c for c in self.calls if c[1]=='GET'])-before,1)
        bad=WorkOSConnectVerifier(self.config,'mcp',fetch_json=lambda *a,**k:{'keys':[self.jwk,self.jwk]})
        with self.assertRaises(ValueError):bad.verify_access(self.token())

    def test_configuration_requires_two_distinct_clients_and_exact_endpoints(self):
        for change in [dict(owner_client_id='client_mcp'),dict(introspection_url='https://other.test/introspect'),dict(issuer='http://localhost'),dict(issuer=self.config['issuer']+'/'),dict(owner_resource=self.config['public_url'])]:
            with self.subTest(change=change),self.assertRaises(ValueError):WorkOSConnectVerifier(dict(self.config,**change),'mcp')

    def test_expired_jwks_fetch_failure_does_not_extend_stale_cache(self):
        from rumbo.workos import KEY_TTL
        now=[time.time()]
        self.claims['exp']=int(now[0])+3600
        calls=[]
        def fetch(*args,**kwargs):
            calls.append(args[0])
            if args[0].endswith('/jwks') and len([u for u in calls if u.endswith('/jwks')])>1:
                raise OSError('Synthetic network failure')
            return self.fetch(*args,**kwargs)
        verifier=WorkOSConnectVerifier(self.config,'mcp',clock=lambda:now[0],fetch_json=fetch)
        verifier.verify_access(self.token())
        now[0]+=KEY_TTL+1
        for _ in range(2):
            with self.assertRaises(ValueError):verifier.verify_access(self.token())

    @unittest.skipUnless(importlib.util.find_spec('authlib') and importlib.util.find_spec('requests'),
                         'Install requirements-authkit.txt for owner HTTP integration tests')
    def test_http_owner_pkce_nonce_and_mcp_use_separate_verified_credentials(self):
        import http.client, io, re, threading
        from http.cookies import SimpleCookie
        from urllib.parse import urlencode, urlsplit
        from requests import Response
        from rumbo.server import create_server
        from rumbo.core import Engine
        from test_core import contract
        with tempfile.TemporaryDirectory() as root:
            Engine(root,'owner','human').execute('create_contract',contract())
            config=dict(self.config,mode='oauth',principals=[dict(subject='user_fixture',actor='maker',role='worker',root=root)],owner_principals=[dict(subject='user_fixture',actor='owner',root=root)])
            nonce=[''];tokens={};requests_seen=[]
            def provider(url,method='GET',data=None,headers=None):
                if url.endswith('/jwks'):return self.jwks
                body=parse_qs(data.decode());requests_seen.append(body)
                claims=tokens[body['token'][0]]
                expected='client_owner' if claims['aud']==config['owner_resource'] else 'client_mcp'
                self.assertEqual(body['client_id'],[expected])
                self.assertNotIn('Authorization',headers)
                return dict({k:v for k,v in claims.items() if k!='scope'},active=True,token_type='access_token')
            def token_transport(request,**kwargs):
                self.assertEqual(request.url,config['token_endpoint'])
                body=parse_qs(request.body);self.assertEqual(body['client_id'],['client_owner']);self.assertIn('client_secret',body)
                self.assertNotIn('Authorization',request.headers);self.assertIn('code_verifier',body)
                access_claims=dict(self.claims,aud=config['owner_resource'],client_id='client_owner',scope='openid rumbo:owner')
                access=self.token(access_claims);tokens[access]=access_claims
                identity=self.token(dict(iss=config['issuer'],aud='client_owner',sub='user_fixture',iat=self.now-1,exp=self.now+300,nonce=nonce[0]))
                response=Response();response.status_code=200;response.headers['Content-Type']='application/json'
                response._content=json.dumps(dict(access_token=access,id_token=identity,token_type='Bearer')).encode();response.raw=io.BytesIO(response._content);response.url=request.url
                for hook in request.hooks.get('response',[]):hook(response)
                return response
            with patch('rumbo.workos._fetch_json',side_effect=provider),patch('requests.sessions.Session.send',side_effect=token_transport):
                server=create_server('127.0.0.1',0,config);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                def request(method,path,body=None,cookie=None,token=None):
                    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    headers={'Host':'rumbo.test'}
                    if cookie:headers['Cookie']=cookie
                    if token:headers['Authorization']='Bearer '+token
                    if body is not None:headers['Content-Type']='application/json';body=json.dumps(body)
                    connection.request(method,path,body,headers);response=connection.getresponse();out=(response.status,response.getheaders(),response.read());connection.close();return out
                try:
                    discovery=request('GET','/.well-known/oauth-protected-resource')
                    self.assertIn('offline_access',json.loads(discovery[2])['scopes_supported'])
                    status,headers,_=request('GET','/owner/login');self.assertEqual(status,303)
                    query=parse_qs(urlsplit(dict(headers)['Location']).query)
                    self.assertIn('nonce',query)
                    self.assertEqual(set(query['scope'][0].split()),{'openid','rumbo:owner'})
                    nonce[0]=query['nonce'][0];self.assertGreaterEqual(len(nonce[0]),32)
                    cookie=SimpleCookie();cookie.load(dict(headers)['Set-Cookie']);binding='__Host-rumbo-owner-login='+cookie['__Host-rumbo-owner-login'].value
                    callback='/owner/callback?'+urlencode(dict(code='fixture-code',state=query['state'][0]))
                    status,headers,_=request('GET',callback,cookie=binding);self.assertEqual(status,303)
                    cookie=SimpleCookie()
                    for key,value in headers:
                        if key=='Set-Cookie':cookie.load(value)
                    owner_cookie='__Host-rumbo-owner='+cookie['__Host-rumbo-owner'].value
                    self.assertEqual(request('GET','/owner',cookie=owner_cookie)[0],200)
                    self.assertEqual(request('GET',callback,cookie=binding)[0],403)
                    mcp=self.token();tokens[mcp]=self.claims
                    body=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='rumbo_state',arguments={}))
                    self.assertEqual(request('POST','/mcp',body,token=mcp)[0],200)
                    owner_token=next(t for t,c in tokens.items() if c['aud']==config['owner_resource'])
                    self.assertEqual(request('POST','/mcp',body,token=owner_token)[0],401)
                    self.assertEqual(request('POST','/mcp',body,cookie=owner_cookie)[0],401)
                    self.assertEqual({x['client_id'][0] for x in requests_seen},{'client_mcp','client_owner'})
                finally:server.shutdown();server.server_close();thread.join()

    def test_mcp_refresh_scope_adds_no_owner_or_write_authority(self):
        self.claims['scope']='rumbo:read offline_access'
        result=self.verifier.verify_access(self.token())
        self.assertEqual(set(result['scope'].split()),{'rumbo:read','offline_access'})
        self.claims['scope']='offline_access'
        with self.assertRaises(ValueError):self.verifier.verify_access(self.token())
        self.verifier=WorkOSConnectVerifier(self.config,'owner',fetch_json=self.fetch)
        self.claims.update(aud=self.config['owner_resource'],client_id='client_owner',scope='openid rumbo:owner offline_access')
        with self.assertRaises(ValueError):self.verifier.verify_access(self.token())

    def test_missing_secret_never_sends_token(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):self.verifier.verify_access(self.token())
        self.assertFalse(any(c[1]=='POST' for c in self.calls))

if __name__=='__main__':unittest.main()
