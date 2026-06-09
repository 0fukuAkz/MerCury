const puppeteer = require('puppeteer');

(async () => {
    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    
    // Log all console messages
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    
    // Log dialogs
    page.on('dialog', async dialog => {
        console.log('DIALOG APPEARED:', dialog.message());
        await new Promise(resolve => setTimeout(resolve, 500)); // wait a bit
        console.log('ACCEPTING DIALOG');
        await dialog.accept();
    });
    
    console.log('Navigating to login...');
    await page.goto('http://localhost:5050/login', { waitUntil: 'networkidle2' });
    
    console.log('Logging in...');
    await page.type('input[name="username"]', 'admin');
    await page.type('input[name="password"]', 'mercury123'); // assuming default or let's just bypass
    await page.click('button[type="submit"]');
    
    await page.waitForNavigation({ waitUntil: 'networkidle2' });
    console.log('Navigating to recipients...');
    await page.goto('http://localhost:5050/recipients', { waitUntil: 'networkidle2' });
    
    // Upload a dummy file if table is empty
    const wrap = await page.$('#files-table-wrap');
    const html = await page.evaluate(el => el.innerHTML, wrap);
    if (html.includes('No recipient lists')) {
        console.log('Uploading dummy file...');
        // Mock a file upload by calling the API directly via page.evaluate
        await page.evaluate(async () => {
            const fd = new FormData();
            fd.append('file', new File(['email\ntest@example.com'], 'puppeteer_test.csv', { type: 'text/csv' }));
            fd.append('validate', 'false');
            fd.append('deduplicate', 'false');
            await fetch('/api/recipients/upload', { method: 'POST', body: fd });
            loadFiles();
        });
        await new Promise(r => setTimeout(r, 1000));
    }
    
    console.log('Clicking delete button...');
    const delBtn = await page.$('button[data-action="delete"]');
    if (!delBtn) {
        console.log('NO DELETE BUTTON FOUND');
    } else {
        await delBtn.click();
        console.log('Button clicked!');
        await new Promise(r => setTimeout(r, 2000));
        
        // Check if file is still there
        const wrap2 = await page.$('#files-table-wrap');
        const html2 = await page.evaluate(el => el.innerHTML, wrap2);
        console.log('TABLE AFTER DELETE:', html2.includes('puppeteer_test.csv') ? 'FILE STILL THERE' : 'FILE GONE');
    }
    
    await browser.close();
})();
