"""Browser regression: switching runtimes must not mix asynchronous responses."""
import unittest
import re
from pathlib import Path
from playwright.sync_api import sync_playwright


class RuntimeSwitchTests(unittest.TestCase):
    def test_switch_while_child_status_pending_and_start_parent(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            root=Path(__file__).resolve().parents[1]
            frontend=root/'app/web_user/experience'
            html=(frontend/'index.html').read_text(encoding='utf-8')
            page.route('http://127.0.0.1:18119/**',lambda route:route.fulfill(body='<html></html>',content_type='text/html'))
            page.goto('http://127.0.0.1:18119/')
            page.set_content(re.sub(r'<script.*?</script>', '', html))
            page.evaluate("document.body.classList.remove('session-checking')")
            for stylesheet in ['style.css','runtime.css']:
                page.add_style_tag(path=str(frontend/stylesheet))
            page.evaluate('''() => {
                window.names={};window.state={loggedIn:true,pa:{},type:'openclaw',phc:{id:'phc:parent'}};
                window.page=()=>{document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!=='page-partners');};window.notice=()=>{};window.loginRequired=()=>{};
                window.calls=[];window.childResolve=null;
                window.fetch=async (url, options)=>{
                    calls.push({url,method:options.method||'GET'});
                    if(url.includes('/children/'))return {ok:true,status:200,json:async()=>({success:true,children:[{phc_id:'child',name:'学习助手',stage:'idle'}]})};
                    if(url.includes('child/status'))return new Promise(resolve=>childResolve=()=>resolve({
                        ok:true,status:200,json:async()=>({stage:'ready',message:'child ready',url:'http://127.0.0.1:19002',model:'child-model'})}));
                    return {ok:true,status:200,json:async()=>({stage:url.endsWith('/start')?'ready':'idle',
                        message:'parent state',model:'parent-model',url:'http://127.0.0.1:19001'})};
                };
            }''')
            script=Path(__file__).resolve().parents[1]/'app/web_user/experience/runtime.js'
            page.add_script_tag(path=str(script))
            page.wait_for_function("document.querySelector('#runtime-model-name').value==='parent-model'")
            page.evaluate('page()')
            page.locator('[data-agent="child"]').click()
            page.locator('[data-agent="phc_parent"]').click()
            page.wait_for_function("document.querySelector('#runtime-model-name').value==='parent-model'")
            page.evaluate('childResolve()')
            page.wait_for_timeout(100)
            self.assertEqual(page.locator('#runtime-message').inner_text(),'parent state')
            self.assertTrue(page.locator('#runtime-open').is_hidden())
            page.locator('#runtime-start').click()
            page.wait_for_function("document.querySelector('#runtime-open').getAttribute('href')==='http://127.0.0.1:19001/'")
            posts=page.evaluate("calls.filter(c=>c.method==='POST').map(c=>c.url)")
            self.assertEqual(posts,['/user/runtime/phc_parent/start'])
            page.screenshot(path=str(root/'.tmp_frontend_qa/partners-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.assertTrue(page.locator('[data-agent="child"]').is_visible())
            page.screenshot(path=str(root/'.tmp_frontend_qa/partners-mobile.png'),full_page=True)
            page.evaluate('''() => {
                const previous=window.fetch;window.createdPayload=null;
                window.fetch=async(url,options)=>{
                    if(url==='/user/children/create'){
                        createdPayload=JSON.parse(options.body);
                        return {ok:true,status:200,json:async()=>({success:true,child:{phc_id:'new_child',name:'New helper'}})};
                    }
                    if(url.includes('/children/')&&createdPayload)return {ok:true,status:200,json:async()=>({success:true,children:[{phc_id:'new_child',name:'New helper',stage:'idle'}]})};
                    return previous(url,options);
                };
            }''')
            page.add_script_tag(path=str(frontend/'children.js'))
            page.evaluate("state.type='octopus'")
            page.locator('#partners-add').click()
            self.assertTrue(page.locator('.child-create-dialog').is_visible())
            self.assertEqual(page.locator('#child-form input[value="text-processing"]').count(),1)
            self.assertEqual(page.locator('#child-form input[value="shell"]').count(),0)
            page.locator('#child-form input[name="name"]').fill('New helper')
            page.locator('#child-form input[name="description"]').fill('Research notes')
            page.screenshot(path=str(root/'.tmp_frontend_qa/child-create-mobile.png'),full_page=True)
            page.locator('#child-form button').click()
            page.wait_for_function("!document.querySelector('.child-create-dialog').open")
            page.wait_for_function("document.querySelector('[data-agent=\"new_child\"]')?.getAttribute('aria-pressed')==='true'")
            self.assertEqual(page.evaluate('createdPayload.parent_phc_id'),'phc:parent')
            self.assertEqual(page.evaluate('createdPayload.name'),'New helper')
            page.evaluate('''() => {
                window.api=async(url,body)=>{
                    if(url.includes('/children/'))return {children:[{phc_id:'new_child',name:'New helper'}]};
                    if(url.endsWith('/send')){window.anpBody=body;return {receipt:{message_id:'test-receipt'}};}
                    return {connected:true,messages:[{sender_did:'local:new_child',timestamp:'test',content:'Reply received'}]};
                };
            }''')
            page.add_script_tag(path=str(frontend/'anp.js'))
            page.locator('#anp-content').fill('Hello child')
            page.locator('#anp-send').click()
            page.wait_for_function("document.querySelector('#anp-status').textContent.includes('test-receipt')")
            self.assertEqual(page.evaluate('anpBody.target_id'),'new_child')
            page.locator('#anp-refresh').click()
            page.wait_for_function("document.querySelector('#anp-inbox').textContent.includes('Reply received')")
            browser.close()


if __name__ == '__main__':
    unittest.main()
