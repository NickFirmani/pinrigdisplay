"""Bounded native decoder for build-generated RGB565 run/literal blocks."""
import micropython


@micropython.viper
def decode(source, destination, source_size:int, destination_size:int) -> int:
    src=ptr8(source)
    dst=ptr8(destination)
    i=0
    out=0
    while i<source_size:
        if i+2>source_size:return -1
        token=int(src[i])|(int(src[i+1])<<8)
        i+=2
        count=token&32767
        if count==0 or out+count*2>destination_size:return -1
        if token&32768:
            if i+2>source_size:return -1
            a=int(src[i]);b=int(src[i+1]);i+=2
            for j in range(count):
                dst[out]=a;dst[out+1]=b;out+=2
        else:
            end=i+count*2
            if end>source_size:return -1
            while i<end:
                dst[out]=src[i];out+=1;i+=1
    return out
