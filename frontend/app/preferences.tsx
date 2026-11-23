'use client';

import {createContext,useCallback,useContext,useEffect,useState,type ReactNode} from 'react';
import {legacyCopy} from './legacy-copy';

export type Language = 'en'|'zh-CN';
export type Theme = 'light'|'dark'|'system';
const Preferences = createContext({lang:'zh-CN' as Language, theme:'system' as Theme,
  setLang: (_value:Language)=>{}, setTheme: (_value:Theme)=>{}});

export function StudioPreferences({children}:{children:ReactNode}){
  const [lang,changeLanguage]=useState<Language>('zh-CN');
  const [theme,changeTheme]=useState<Theme>('system');
  useEffect(()=>{
    const language=localStorage.getItem('pastpaper-classroom-language');
    const appearance=localStorage.getItem('pastpaper-classroom-theme');
    if(language==='en'||language==='zh-CN')changeLanguage(language);
    else changeLanguage(navigator.language.toLowerCase().startsWith('zh')?'zh-CN':'en');
    if(appearance==='light'||appearance==='dark'||appearance==='system')changeTheme(appearance);
  },[]);
  useEffect(()=>{document.documentElement.dataset.theme=theme;document.documentElement.lang=lang;document.title=lang==='en'?'PastPaper Studio — Study workspace':'PastPaper Studio — 真题学习工作台';},[theme,lang]);
  return <Preferences.Provider value={{lang,theme,
    setLang:value=>{changeLanguage(value);localStorage.setItem('pastpaper-classroom-language',value);},
    setTheme:value=>{changeTheme(value);localStorage.setItem('pastpaper-classroom-theme',value);},
  }}>{children}</Preferences.Provider>;
}

export const useStudioPreferences=()=>useContext(Preferences);
export function studioText(lang:Language,value:string,...args:unknown[]){
  if(lang==='en'&&value==='用户名或密码不正确')return 'Incorrect username or password.';
  if(lang==='en'&&value==='电子邮箱或密码不正确')return 'Incorrect email address or password.';
  if(lang==='en'&&value==='此账号已由管理员停用')return 'This account is disabled.';
  if(lang==='en'&&value==='请联系管理员创建账号')return 'Contact your administrator to create an account.';
  const text=lang==='en'?legacyCopy[value]||value:value;
  return args.length ? text.replace(/\{(\d+)\}/g,(_,index)=>String(args[Number(index)]??'')) : text;
}
export function localizedStatus(lang:Language,value:string){
  const text=studioText(lang,value);
  return lang==='en'&&/\p{Script=Han}/u.test(text)?'See the source file or try the action again for details.':text;
}
export function useStudioText(){
  const {lang}=useStudioPreferences();
  return useCallback((value:string,...args:unknown[])=>studioText(lang,value,...args),[lang]);
}
export function useStudioStatus(){
  const {lang}=useStudioPreferences();
  return (value:string)=>localizedStatus(lang,value);
}
export const roleLabel=(role:string,english:boolean)=>({
  admin:english?'Administrator':'管理员',teacher:english?'Teacher':'老师',student:english?'Student':'学生',
}[role]||role);

export function HeaderLanguageSwitch(){
  const {lang,setLang}=useStudioPreferences();
  return <div className="topbar-language" role="group" aria-label={lang==='en'?'Language':'语言'}>
    <button type="button" lang="en" aria-pressed={lang==='en'} onClick={()=>setLang('en')}>English</button>
    <button type="button" aria-pressed={lang==='zh-CN'} onClick={()=>setLang('zh-CN')}>{lang==='en'?'Chinese':'中文'}</button>
  </div>;
}

export function PreferenceControls({appearanceOnly=false}:{appearanceOnly?:boolean}){
  const {lang,theme,setLang,setTheme}=useStudioPreferences();
  const en=lang==='en';
  return <div className="work-actions studio-preferences">
    {!appearanceOnly&&<label>{en?'Language':'语言'}<select value={lang} onChange={event=>setLang(event.target.value as Language)}>
      <option value="en">English</option><option value="zh-CN">{en?'Simplified Chinese':'简体中文'}</option>
    </select></label>}
    <label>{en?'Appearance':'外观'}<select value={theme} onChange={event=>setTheme(event.target.value as Theme)}>
      <option value="system">{en?'System':'跟随系统'}</option><option value="light">{en?'Light':'浅色'}</option><option value="dark">{en?'Dark':'深色'}</option>
    </select></label>
  </div>;
}
