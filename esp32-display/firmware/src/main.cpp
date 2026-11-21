#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <Network.h>
#include <WiFi.h>
#include <Preferences.h>
#include <esp_rom_crc.h>

// Same panel, offset and QSPI pins as DragonRadar/ui/UiDeviceOwner.cpp.
constexpr unsigned W = 466, H = 466, BYTES = W * H * 2;
Arduino_ESP32QSPI bus(12, 38, 4, 5, 6, 7);
Arduino_CO5300 panel(&bus, GFX_NOT_DEFINED, 0, W, H, 6, 0, 0, 0);
WiFiServer server(19750);
WiFiClient client;
uint8_t *front = nullptr, *back = nullptr;
uint32_t lastFrame = 0, frames = 0;
bool stale = true;
String serialLine;
uint16_t rectangles[225][4];
uint16_t tilePixels[32*32];

uint16_t u16(const uint8_t *p) { return p[0] | (uint16_t(p[1]) << 8); }
uint32_t u32(const uint8_t *p) { return u16(p) | (uint32_t(u16(p + 2)) << 16); }
void put32(uint8_t *p, uint32_t n) { for (int i=0;i<4;i++) p[i]=n>>(8*i); }
bool readExact(uint8_t *p, size_t n) {
  uint32_t start=millis();
  while(n && client.connected() && millis()-start<2000) {
    int got=client.read(p,n);
    if(got>0) {p+=got;n-=got;} else delay(1);
  }
  return n==0;
}
void message(const char *a, const char *b) {
  panel.fillScreen(0);
  panel.setTextColor(0xA7E9); panel.setTextSize(3);
  panel.setCursor(105,195); panel.println(a);
  panel.setTextSize(2); panel.setCursor(75,240); panel.println(b);
}
void receiveFrame() {
  uint8_t h[20];
  if(!readExact(h,sizeof h) || memcmp(h,"ASU1",4)) {client.stop();return;}
  uint32_t seq=u32(h+4), remaining=u32(h+8), expected=u32(h+12), count=u32(h+16);
  if(count>225 || remaining>BYTES+225*8) {client.stop();return;}
  memcpy(back,front,BYTES);
  for(uint32_t t=0;t<count;t++) {
    uint8_t tile[8];
    if(remaining<8 || !readExact(tile,8)) {client.stop();return;}
    remaining-=8;
    unsigned x=u16(tile), y=u16(tile+2), w=u16(tile+4), height=u16(tile+6);
    if(!w || !height || w>32 || height>32 || x+w>W || y+height>H || w*height*2>remaining) {client.stop();return;}
    rectangles[t][0]=x;rectangles[t][1]=y;rectangles[t][2]=w;rectangles[t][3]=height;
    for(unsigned row=0;row<height;row++) {
      if(!readExact(back+((y+row)*W+x)*2,w*2)) {client.stop();return;}
    }
    remaining-=w*height*2;
  }
  uint32_t actual=esp_rom_crc32_le(0,back,BYTES);
  if(remaining || actual!=expected) {Serial.println("FRAME_REJECT crc/length");client.stop();return;}
  uint32_t start=millis();
  if(stale || count>100) {
    panel.draw16bitRGBBitmap(0,0,reinterpret_cast<uint16_t*>(back),W,H);
  } else {
    for(uint32_t t=0;t<count;t++) {
      unsigned x=rectangles[t][0],y=rectangles[t][1],w=rectangles[t][2],height=rectangles[t][3];
      for(unsigned row=0;row<height;row++) memcpy(tilePixels+row*w,back+((y+row)*W+x)*2,w*2);
      panel.draw16bitRGBBitmap(x,y,tilePixels,w,height);
    }
  }
  std::swap(front,back);
  lastFrame=millis(); stale=false; frames++;
  uint8_t ack[16]; memcpy(ack,"ACK1",4);put32(ack+4,seq);put32(ack+8,actual);put32(ack+12,millis()-start);
  client.write(ack,sizeof ack);
  if(frames%50==1) Serial.printf("FRAME_OK seq=%lu crc=%08lx draw_ms=%lu heap=%u\n",(unsigned long)seq,(unsigned long)actual,(unsigned long)(millis()-start),ESP.getFreeHeap());
}
void setup() {
  Serial.begin(115200);
  pinMode(46,OUTPUT);digitalWrite(46,LOW); // keep speaker amplifier muted
  pinMode(2,OUTPUT);digitalWrite(2,HIGH);delay(10);digitalWrite(2,LOW);delay(120);digitalWrite(2,HIGH);delay(120);
  if(!panel.begin(80000000)) {Serial.println("DISPLAY_FAILED");while(true)delay(1000);}
  panel.setBrightness(180);
  front=(uint8_t*)ps_calloc(1,BYTES); back=(uint8_t*)ps_malloc(BYTES);
  if(!front || !back) {message("MEMORY ERROR","PSRAM required");while(true)delay(1000);}
  Preferences p;p.begin("asurada-display",true);
  String ssid=p.getString("ssid"), pass=p.getString("pass");p.end();
  WiFi.mode(WIFI_AP_STA);WiFi.setSleep(false);
  WiFi.softAP("Asurada-Display","Asurada19750");
  if(ssid.length()) WiFi.begin(ssid.c_str(),pass.c_str());
  server.begin();server.setNoDelay(true);
  message("ASURADA","Wi-Fi: Asurada-Display");
  Serial.println("ASURADA_DISPLAY CO5300 466x466 TCP19750 AP=192.168.4.1");
}
void loop() {
  // Provision without embedding credentials in source. Command: WIFI<TAB>ssid<TAB>password<NEWLINE>
  while(Serial.available()) {
    char c=Serial.read();
    if(c=='\n') {
      if(serialLine.startsWith("WIFI\t")) {
        int split=serialLine.indexOf('\t',5);
        if(split>5) {
          String ssid=serialLine.substring(5,split),pass=serialLine.substring(split+1);
          Preferences p;p.begin("asurada-display",false);p.putString("ssid",ssid);p.putString("pass",pass);p.end();
          WiFi.begin(ssid.c_str(),pass.c_str());Serial.println("WIFI_CONFIGURED");
        }
      }
      if(serialLine=="STATUS") Serial.printf("STATUS ip=%s frames=%lu stale=%d\n",WiFi.localIP().toString().c_str(),(unsigned long)frames,stale);
      serialLine="";
    } else if(c!='\r') { if(serialLine.length()<180)serialLine+=c;else serialLine=""; }
  }
  if(!client.connected()) {client=server.accept(); if(client) {client.setNoDelay(true);memset(front,0,BYTES);}}
  if(client && client.available()) receiveFrame();
  if(!stale && millis()-lastFrame>2500) {message("LINK LOST","Waiting for live feed");stale=true;}
  delay(1);
}
