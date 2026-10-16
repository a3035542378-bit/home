"""生成隔离 DEBUG_ONLY 桥脚本，通过原版工厂打开真灵界面。"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


MARKER = "configureRoleWire(game,offlineStore,isPreparedPetRequest);"
INSTALL = "\ntry{configureDebugTrueSpiritEntry(game,offlineStore);}catch(error){report({event:'DEBUG_ONLY-entry-setup-failed',error:error.message});}"
DEBUG = r"""
function configureDebugTrueSpiritEntry(game,store){
 const entry=game.base.add(0x26acd0c);
 if(Process.arch!=='arm64'||entry.readU32()!==0xd10043ff||entry.add(4).readU32()!==0xa9007bf3)throw new Error('DEBUG_ONLY true spirit constructor fingerprint mismatch');
 const construct=new NativeFunction(entry,'void',['pointer']);
 const allocate=new NativeFunction(game.getExportByName('_Znwm'),'pointer',['ulong']);
 const autorelease=new NativeFunction(game.getExportByName('_ZN7cocos2d8CCObject11autoreleaseEv'),'pointer',['pointer']);
 const addChild=new NativeFunction(game.getExportByName('_ZN7cocos2d6CCNode8addChildEPS0_ii'),'void',['pointer','pointer','int','int']);
 const fileUtils=new NativeFunction(game.getExportByName('_ZN7cocos2d11CCFileUtils15sharedFileUtilsEv'),'pointer',[]);
 const addPath=new NativeFunction(game.getExportByName('_ZN7cocos2d11CCFileUtils13addSearchPathEPKc'),'void',['pointer','pointer']);
 const access=new NativeFunction(Module.getExportByName('libc.so','access'),'int',['pointer','int']);
 const unlink=new NativeFunction(Module.getExportByName('libc.so','unlink'),'int',['pointer']);
 const trigger=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY_true_spirit_entry');
 const send=game.base.add(0x2c16994);
 if(send.readU32()!==0xd63f00c0)throw new Error('DEBUG_ONLY fusion sender fingerprint mismatch');
 Interceptor.attach(send,{onEnter(){
  const request=store.readRequest(this.context.x2),fields={};
  for(const key of ['rid','main_pet','auxiliary_pet','directed_material','evolution_material','green_type','is_common_fusion','is_use_sheep'])if(key in request)fields[key]=request[key];
  report({event:'DEBUG_ONLY-original-fusion-request',command:458,fields});
 }});
 let lastCheck=0,lastScene=null;
 Interceptor.attach(game.getExportByName('_ZN7cocos2d10CCDirector9drawSceneEv'),{onEnter(){
  if(Date.now()-lastCheck<500)return;
  lastCheck=Date.now();
  const global=game.base.add(0x67b85d0).readPointer();
  if(global.isNull())return;
  const scene=global.add(0x270).readPointer();
  if(access(trigger,0)===0&&!scene.isNull()){
   const type=scene.readPointer().sub(game.base).toString();
   if(type!==lastScene){lastScene=type;report({event:'DEBUG_ONLY-current-scene-type',offset:type});}
  }
  if(scene.isNull()||!scene.readPointer().equals(game.base.add(0x67086e0)))return;
  if(access(trigger,0)!==0)return;
  if(unlink(trigger)!==0)throw new Error('DEBUG_ONLY trigger could not be consumed');
  report({event:'DEBUG_ONLY-true-spirit-entry-requested'});
  const grant=Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY_grant_fusion_materials');
  if(access(grant,0)===0){
   if(unlink(grant)!==0)throw new Error('DEBUG_ONLY material trigger could not be consumed');
   const ctor=new NativeFunction(game.base.add(0x3d28344),'void',['pointer','int']);
   const readerCtor=new NativeFunction(game.base.add(0x3d23f04),'void',['pointer']);
   const readerDtor=new NativeFunction(game.base.add(0x211e004),'void',['pointer']);
   const dtor=new NativeFunction(game.base.add(0x3d2a33c),'void',['pointer']);
   const parse=new NativeFunction(game.base.add(0x3d27110),'uint',['pointer','pointer','pointer','pointer','int']);
   const bag=new NativeFunction(game.base.add(0x2d1f964),'pointer',[])();
   const factory=new NativeFunction(game.base.add(0x3c6b750),'pointer',['pointer']);
   const cast=new NativeFunction(game.base.add(0x4ffd82c),'pointer',['pointer','pointer','pointer','long']);
   const retain=new NativeFunction(game.base.add(0x4e13d28),'void',['pointer']);
   const release=new NativeFunction(game.base.add(0x4e13da8),'void',['pointer']);
   const add=new NativeFunction(game.base.add(0x2d41900),'bool',['pointer','pointer','pointer','uint8','uint8','uint8']);
   for(const id of [503344,503345,503346,503347]){
    const text=JSON.stringify({A2:id,A4:100}),data=Memory.allocUtf8String(text),value=Memory.alloc(0x18),reader=Memory.alloc(0xe0);
    value.writeByteArray(new Uint8Array(0x18));reader.writeByteArray(new Uint8Array(0xe0));
    ctor(value,0);readerCtor(reader);
    try{
     if(!parse(reader,data,data.add(text.length),value,1))throw new Error('DEBUG_ONLY material JSON failed');
     const object=factory(value);
     if(object.isNull())throw new Error('DEBUG_ONLY native material factory failed');
     retain(object);
     try{
      const item=cast(object,game.base.add(0x67784d0).readPointer(),game.base.add(0x677f968).readPointer(),0);
      if(item.isNull()||!add(bag,item,bag,0,1,0))throw new Error('DEBUG_ONLY native material grant failed');
     }finally{release(object);}
    }finally{dtor(value);readerDtor(reader);}
   }
   report({event:'DEBUG_ONLY-native-fusion-materials-granted'});
  }
  addPath(fileUtils(),Memory.allocUtf8String('/data/user/0/com.zmxyol.union.uc/files/DEBUG_ONLY-assets/'));
  const child=new NativeFunction(game.getExportByName('_ZN7cocos2d6CCNode13getChildByTagEi'),'pointer',['pointer','int']);
  if(!child(scene,7798).isNull())throw new Error('DEBUG_ONLY board already open');
  const layer=allocate(0x220);
  construct(layer);
  if(!layer.readPointer().equals(game.base.add(0x5fd87c0)))throw new Error('DEBUG_ONLY wrong board type');
  const init=new NativeFunction(layer.readPointer().add(0x38).readPointer(),'bool',['pointer']);
  if(!init(layer))throw new Error('DEBUG_ONLY original board initialization failed');
  autorelease(layer);
  addChild(scene,layer,9001,7798);
  const thunk=Memory.alloc(Process.pageSize);
  if(!Memory.protect(thunk,Process.pageSize,'r-x'))throw new Error('DEBUG_ONLY serializer allocation failed');
  Memory.patchCode(thunk,8,code=>{code.writeU32(0xaa0103e8);code.add(4).writeU32(0xd61f0040);});
  const serialize=new NativeFunction(thunk,'void',['pointer','pointer','pointer']);
  const getBag=new NativeFunction(game.base.add(0x2d1f964),'pointer',[]);
  const destroy=new NativeFunction(game.base.add(0x3d2a33c),'void',['pointer']);
  const snapshot=Memory.alloc(0x18);
  serialize(getBag(),snapshot,game.base.add(0x2d4053c));
  try{
   const bag=store.readRequest(snapshot);
   report({event:'DEBUG_ONLY-fusion-material-snapshot',items:bag.item.filter(item=>[503344,503345,503346,503347].includes(item.A2)),counters:Object.fromEntries(Object.entries(bag).filter(([key,value])=>typeof value==='number'))});
  }
  finally{destroy(snapshot);}
  report({event:'DEBUG_ONLY-true-spirit-entry-returned',created:true});
 }});
 report({event:'DEBUG_ONLY-true-spirit-entry-ready'});
}
"""


def build_debug_script(source: str) -> str:
    if source.count(MARKER) != 1 or "configureDebugTrueSpiritEntry" in source:
        raise ValueError("Expected one unmodified production configure function")
    return DEBUG + source.replace(MARKER, MARKER + INSTALL, 1)


async def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    script = build_debug_script(args.source.read_text(encoding="utf-8"))
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(script)


if __name__ == "__main__":
    asyncio.run(run())
