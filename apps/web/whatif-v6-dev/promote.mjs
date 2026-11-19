import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const source=path.join(root,'dist','whatif-v6');
const destination=path.resolve(root,'..','quote-monitor','site','whatif-v6');
if(!fs.existsSync(path.join(source,'index.html'))){
  console.error('먼저 npm run build 또는 npm run dev로 빌드하세요.');
  process.exit(1);
}
fs.cpSync(source,destination,{recursive:true,force:true});
console.log(`배포 입력 폴더에 복사했습니다: ${destination}`);
