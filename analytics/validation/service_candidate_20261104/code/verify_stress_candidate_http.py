"""Start only this candidate on an ephemeral localhost port, exercise, then stop."""
import json,os,socket,subprocess,sys,time,urllib.request
from service_candidate_20261104 import OUT

def main():
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    folder=OUT/'service';url=f'http://127.0.0.1:{port}'
    log=(OUT/'local_http.log').open('w',encoding='utf8')
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],cwd=folder,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(url+'/health',timeout=1) as r:health=json.load(r)
                break
            except Exception:
                if process.poll() is not None:raise RuntimeError('Candidate server exited; inspect local_http.log')
                time.sleep(.25)
        else:raise RuntimeError('Candidate startup timeout')
        payload=(folder/'request.json').read_bytes();request=urllib.request.Request(url+'/stress',data=payload,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=10) as r:result=json.load(r);status=r.status
        assert status==200 and len(result['assets'])==2 and result['input_shocks']['vix_change_points']==0
        (OUT/'http_response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        (OUT/'http_verification.json').write_text(json.dumps(dict(passed=True,real_local_http=True,status=status,model=health['model_version'],state_date=health['state_date'],azure_changed=False,existing_servers_stopped=False),indent=2))
        print(json.dumps(dict(status=status,model=health['model_version'],pnl=result['hypothetical_portfolio_pnl_krw'])))
    finally:
        process.terminate();process.wait(timeout=10);log.close()

if __name__=='__main__':main()
