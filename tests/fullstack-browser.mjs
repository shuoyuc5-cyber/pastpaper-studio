import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';

const modulePath = process.env.PASTPAPER_TEST_PLAYWRIGHT;
const {chromium} = await import(pathToFileURL(path.join(modulePath,'index.mjs')));
const origin = process.env.PASTPAPER_TEST_ORIGIN;
const evidence = process.env.PASTPAPER_TEST_EVIDENCE;
assert.match(origin, /^https:\/\/127\.0\.0\.1:\d+$/);
const browser = await chromium.launch({headless:true, executablePath:process.env.PASTPAPER_TEST_CHROME || undefined});
try {
  for (const [name, width, height, mobile] of [
    ['desktop',1440,960,false], ['tablet',820,1180,true], ['phone',390,844,true],
  ]) {
    const context = await browser.newContext({viewport:{width,height}, isMobile:mobile, hasTouch:mobile,
                                               ignoreHTTPSErrors:true});
    await context.addInitScript(() => localStorage.setItem('pastpaper-classroom-language','en'));
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin);
    await page.getByRole('textbox',{name:'Email address', exact:false}).fill('student@example.test');
    await page.getByLabel('Password',{exact:true}).fill(process.env.PASTPAPER_TEST_STUDENT_PASSWORD);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:'Student dashboard'}).waitFor();
    await page.reload();
    await page.getByRole('heading',{name:'Student dashboard'}).waitFor();
    await page.getByRole('button',{name:'Question search',exact:true}).click();
    const filter = page.locator('.work-filters');
    await filter.getByRole('textbox').first().fill('probability');
    await filter.getByRole('button',{name:'Search',exact:true}).click();
    const card = page.locator('.question-card').first();
    await card.waitFor();
    await card.locator('img').first().scrollIntoViewIfNeeded();
    await page.waitForFunction(() => [...document.querySelectorAll('.question-card img')]
      .some(img => img.complete && img.naturalWidth > 0));
    assert.equal(await page.getByRole('button',{name:'User Management'}).count(),0);
    assert.equal(await page.getByRole('button',{name:'Import',exact:true}).count(),0);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({path:path.join(evidence,`student-${name}.png`), fullPage:true});
    await page.getByRole('button',{name:'Student dashboard',exact:true}).click();
    await page.getByRole('button',{name:'Open class',exact:true}).first().click();
    await page.getByText('Algebra practice',{exact:true}).first().waitFor();
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`PASS browser ${name} ${width}x${height} | sign in, reload, role gating, English search, original question image, existing class assignment`);
  }
  const teacher = await browser.newContext({viewport:{width:1440,height:960},ignoreHTTPSErrors:true});
  await teacher.addInitScript(() => localStorage.setItem('pastpaper-classroom-language','en'));
  const page = await teacher.newPage();
  await page.goto(origin);
  await page.getByRole('textbox',{name:'Email address'}).fill('teacher@example.test');
  await page.getByLabel('Password',{exact:true}).fill(process.env.PASTPAPER_TEST_TEACHER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Teaching dashboard'}).waitFor();
  await page.getByRole('button',{name:'Import',exact:true}).click();
  await page.getByLabel('Select PDF folder').setInputFiles(path.join(evidence,'browser-fixtures'));
  await page.getByText(/non-PDF files/).waitFor();
  await page.getByRole('button',{name:/Import selected PDFs/}).click();
  await page.waitForFunction(async () => {
    const response = await fetch('/api/imports', {cache:'no-store'});
    if (!response.ok) return false;
    return (await response.json()).files.some(file=>file.filename==='0580_s26_qp_21.pdf' && file.status==='completed');
  });
  await teacher.close();
  console.log('PASS browser teacher | folder picker review ignores non-PDF, then durable PDF import finishes');
} finally {
  await browser.close();
}
