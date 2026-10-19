import fs from 'fs';
import path from 'path';

function getFiles(dir, fileList = []) {
    if (!fs.existsSync(dir)) return fileList;
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const filePath = path.join(dir, file);
        if (fs.statSync(filePath).isDirectory()) {
            getFiles(filePath, fileList);
        } else {
            fileList.push(filePath);
        }
    }
    return fileList;
}

const files = getFiles('bundle_staging');
const patterns = [
    /AKIA[0-9A-Z]{16}/,
    /eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+/,
    /sk-[A-Za-z0-9]{16,}/,
    /ghp_[A-Za-z0-9]{20,}/,
    /gho_[A-Za-z0-9]{20,}/,
    /Bearer\s+[A-Za-z0-9._\-]{24,}/,
    /[A-Za-z]:[\\\/]+Users[\\\/]+(?!(?:example|Public|Default)[\\\/])[^\\\/\n\r]+[\\\/]/i,
    /(?:Users|home)\/(?!(?:example|public)[\\\/])[^\\\/\n\r]+\//i,
    /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/
];

const allowedEmails = ['anchor@localhost', 'noreply@anthropic.com', 'example.com', 'example.org'];

let hasHit = false;
for (const file of files) {
    // Only scan text files
    const ext = path.extname(file).toLowerCase();
    if (['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.ico', '.woff', '.woff2', '.ttf'].includes(ext)) continue;

    try {
        const content = fs.readFileSync(file, 'utf8');
        for (const pattern of patterns) {
            const match = content.match(pattern);
            if (match) {
                if (match[0].includes('@')) {
                    if (allowedEmails.some(e => match[0].endsWith(e))) continue;
                }
                console.error(`Leak scan hit in ${file}: matched pattern ${pattern.source} -> ${match[0]}`);
                hasHit = true;
            }
        }
    } catch(e) {}
}

if (hasHit) {
    console.error("Leak scan failed. One hit blocks — never patch-and-ship.");
    process.exit(1);
} else {
    console.log("Leak scan passed.");
}
