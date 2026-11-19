"""Atomic LittleFS outbox replacement. Keep eight unconfirmed touch receipts."""
import json
import os


class Outbox:
    def __init__(self,path='interactions.json'):
        self.path=path
        try:
            with open(path) as f:self.items=json.load(f)
        except OSError as error:
            if error.args[0]!=2:raise
            self.items=[]
        if not isinstance(self.items,list) or len(self.items)>8:
            raise ValueError('invalid acknowledgment outbox')

    def save(self,items):
        with open(self.path+'.tmp','w') as f:
            json.dump(items,f)
            f.flush()
        os.sync()
        os.rename(self.path+'.tmp',self.path)
        os.sync()
        self.items=items

    def append(self,item):
        if len(self.items)>=8:raise OSError('acknowledgment outbox full')
        self.save(self.items+[item])

    def pending(self):return list(self.items)

    def confirm(self,interaction_id):
        items=[i for i in self.items if i['interaction_id']!=interaction_id]
        if items!=self.items:self.save(items)
