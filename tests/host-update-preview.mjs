// Loopback-only proxies for real browser checks against the disposable Host fixture.
import http from 'node:http';
import {readFile} from 'node:fs/promises';

const upstreamPort=Number(process.env.HOST_WEB_QA_PORT||39431);
for(const [port,host,folder] of [[Number(process.env.HOST_CLIENT_QA_PORT||39432),'192.168.254.91',false],[Number(process.env.HOST_FOLDER_QA_PORT||39433),'127.0.0.1',true]]){
  http.createServer(async(req,res)=>{
    if(folder&&req.url==='/__qa/folder.mjs'){
      return res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'no-store'}).end(await readFile(new URL('./host-update-browser.mjs',import.meta.url)));
    }
    if(folder&&req.url==='/__qa/share-fixture.mjs'){
      return res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'no-store'}).end(await readFile(new URL('./share-fixture.mjs',import.meta.url)));
    }
    const hostname=host+':'+upstreamPort;
    const headers={...req.headers,host:hostname};
    if(headers.origin==='http://127.0.0.1:'+port)headers.origin='http://'+hostname;
    delete headers['accept-encoding'];
    const upstream=http.request({hostname:'127.0.0.1',port:upstreamPort,path:req.url,method:req.method,headers},response=>{
      const downstream={...response.headers};
      if(folder&&req.method==='GET'&&req.url==='/?qa=folder'&&String(downstream['content-type']).includes('text/html')){
        const chunks=[];
        response.on('data',chunk=>chunks.push(chunk));
        response.on('end',()=>{
          delete downstream['content-length'];delete downstream.etag;
          res.writeHead(response.statusCode,downstream).end(Buffer.concat(chunks).toString().replace('</body>','<script type="module" src="/__qa/folder.mjs"></script></body>'));
        });
      }else{res.writeHead(response.statusCode,downstream);response.pipe(res);}
    });
    upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502).end();else res.destroy();});
    req.pipe(upstream);
  }).listen(port,'127.0.0.1',()=>console.log('Host QA proxy at http://127.0.0.1:'+port));
}
