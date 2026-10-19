import fs from 'fs';
import path from 'path';

function getFiles(dir, fileList = []) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const filePath = path.join(dir, file);
        if (fs.statSync(filePath).isDirectory()) {
            getFiles(filePath, fileList);
        } else {
            fileList.push(filePath.replace(/\\/g, '/'));
        }
    }
    return fileList;
}

function globToRegex(glob) {
    let regex = glob.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    regex = regex.replace(/\\\*\\\*/g, '.*').replace(/\\\*/g, '[^/]*');
    return new RegExp('^' + regex + '$');
}

const manifestContent = fs.readFileSync('bundle/MANIFEST', 'utf8').split('\n');
const shippedGlobs = [];
const notShippedGlobs = [];

for (const line of manifestContent) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    if (trimmed.startsWith('- ')) {
        notShippedGlobs.push(globToRegex(trimmed.slice(2)));
    } else {
        shippedGlobs.push(globToRegex(trimmed));
    }
}

const allFiles = getFiles('.').filter(f => !f.startsWith('.git/'));
let hasError = false;
const stagedDir = 'bundle_staging';

if (fs.existsSync(stagedDir)) fs.rmSync(stagedDir, {recursive: true, force: true});
fs.mkdirSync(stagedDir);

for (const file of allFiles) {
    if (file.startsWith(stagedDir + '/')) continue;

    const isShipped = shippedGlobs.some(r => r.test(file));
    const isNotShipped = notShippedGlobs.some(r => r.test(file));

    if (isShipped) {
        const dest = path.join(stagedDir, file);
        fs.mkdirSync(path.dirname(dest), {recursive: true});
        fs.copyFileSync(file, dest);
    } else if (!isNotShipped) {
        console.error(`Error: File '${file}' is neither listed as shipped nor explicitly marked not-shipped in bundle/MANIFEST.`);
        hasError = true;
    }
}

if (hasError) {
    console.error("Bundle build failed: unlisted files detected. Build fails closed.");
    process.exit(1);
} else {
    console.log("Bundle built successfully in bundle_staging/");
}
