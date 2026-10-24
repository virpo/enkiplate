#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdio.h>
#include <string.h>
static int number(io_service_t s,const char *name){
 CFStringRef key=CFStringCreateWithCString(NULL,name,kCFStringEncodingUTF8);
 CFTypeRef value=IORegistryEntryCreateCFProperty(s,key,NULL,0);CFRelease(key);
 int n=-1;if(value&&CFGetTypeID(value)==CFNumberGetTypeID())CFNumberGetValue((CFNumberRef)value,kCFNumberIntType,&n);
 if(value)CFRelease(value);return n;
}
int main(int argc,char**argv){
 io_iterator_t it=0;io_service_t service=0,target=0;int matches=0;
 kern_return_t kr=IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching(kIOUSBDeviceClassName),&it);
 if(kr){printf("USB lookup: 0x%x\n",kr);return 1;}
 while((service=IOIteratorNext(it))){
  if(number(service,"idVendor")==0x1a86&&number(service,"idProduct")==0x7523){
   matches++;if(!target)target=service;else IOObjectRelease(service);
  }else IOObjectRelease(service);
 }
 IOObjectRelease(it);
 if(matches!=1){printf("Expected exactly one CH340 adapter, found %d. No reset.\n",matches);if(target)IOObjectRelease(target);return 2;}
 printf("Matched CH340 adapter 1a86:7523 at location 0x%x\n",number(target,"locationID"));fflush(stdout);
 if(argc!=2||strcmp(argv[1],"--reset")){IOObjectRelease(target);return 0;}
 IOCFPlugInInterface **plugin=NULL;SInt32 score=0;
 kr=IOCreatePlugInInterfaceForService(target,kIOUSBDeviceUserClientTypeID,kIOCFPlugInInterfaceID,&plugin,&score);IOObjectRelease(target);
 if(kr||!plugin){printf("USB interface unavailable: 0x%x\n",kr);return 3;}
 IOUSBDeviceInterface320 **device=NULL;
 HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID320),(LPVOID*)&device);IODestroyPlugInInterface(plugin);
 if(hr||!device){printf("USB interface query: 0x%x\n",(unsigned)hr);return 4;}
 kr=(*device)->USBDeviceOpen(device);
 if(kr){printf("USB open denied: 0x%x. No reset or permission change.\n",kr);(*device)->Release(device);return 5;}
 kr=(*device)->USBDeviceReEnumerate(device,0);
 printf("USB re-enumeration result: 0x%x\n",kr);
 (*device)->USBDeviceClose(device);(*device)->Release(device);
 return kr?6:0;
}
