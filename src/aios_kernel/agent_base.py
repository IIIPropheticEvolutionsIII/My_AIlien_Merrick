import copy
import logging
from enum import Enum
import uuid
import time 
import re
import shlex
from typing import List
from .ai_function import FunctionItem

logger = logging.getLogger(__name__)

class AgentMsgType(Enum):
    TYPE_MSG = 0
    TYPE_GROUPMSG = 1
    TYPE_INTERNAL_CALL = 10
    TYPE_ACTION = 20
    TYPE_EVENT = 30
    TYPE_SYSTEM = 40


class AgentMsgStatus(Enum):
    RESPONSED = 0
    INIT = 1
    SENDING = 2
    PROCESSING = 3
    ERROR = 4
    RECVED = 5
    EXECUTED = 6

# msg is a msg / msg resp
# msg body可以有内容类型（MIME标签），text, image, voice, video, file,以及富文本(html)
# msg is a inner function call with result
# msg is a Action with result

# qutoe Msg
# forword msg
# reply msg

# 逻辑上的同一个Message在同一个session中看到的msgid相同
#       在不同的session中看到的msgid不同

class AgentMsg:
    def __init__(self,msg_type=AgentMsgType.TYPE_MSG) -> None:
        self.msg_id = "msg#" + uuid.uuid4().hex
        self.msg_type:AgentMsgType = msg_type
        
        self.prev_msg_id:str = None
        self.quote_msg_id:str = None    
        self.rely_msg_id:str = None # if not none means this is a respone msg
        self.session_id:str = None

        #forword info


        self.create_time = 0
        self.done_time = 0
        self.topic:str = None # topic is use to find session, not store in db

        self.sender:str = None # obj_id.sub_objid@tunnel_id
        self.target:str = None
        self.mentions:[] = None #use in group chat only
        #self.title:str = None
        self.body:str = None
        self.body_mime:str = None #//default is "text/plain",encode is utf8

        #type is call / action
        self.func_name = None 
        self.args = None
        self.result_str = None

        #type is event
        self.event_name = None
        self.event_args = None

        self.status = AgentMsgStatus.INIT
        self.inner_call_chain = []
        self.resp_msg = None

    @classmethod
    def create_internal_call_msg(self,func_name:str,args:dict,prev_msg_id:str,caller:str):
        msg = AgentMsg(AgentMsgType.TYPE_INTERNAL_CALL)
        msg.create_time = time.time()
        msg.func_name = func_name
        msg.args = args
        msg.prev_msg_id = prev_msg_id
        msg.sender = caller
        return msg
    
    def create_action_msg(self,action_name:str,args:dict,caller:str):
        msg = AgentMsg(AgentMsgType.TYPE_ACTION)
        msg.create_time = time.time()
        msg.func_name = action_name
        msg.args = args
        msg.prev_msg_id = self.msg_id
        msg.topic  = self.topic
        msg.sender = caller
        return msg
    
    def create_error_resp(self,error_msg:str):
        resp_msg = AgentMsg(AgentMsgType.TYPE_SYSTEM)
        resp_msg.create_time = time.time()
        
        resp_msg.rely_msg_id = self.msg_id
        resp_msg.body = error_msg
        resp_msg.topic  = self.topic
        resp_msg.sender = self.target
        resp_msg.target = self.sender

        return resp_msg

    def create_resp_msg(self,resp_body):
        resp_msg = AgentMsg()
        resp_msg.create_time = time.time()

        resp_msg.rely_msg_id = self.msg_id
        resp_msg.sender = self.target
        resp_msg.target = self.sender
        resp_msg.body = resp_body
        resp_msg.topic = self.topic

        return resp_msg
    
    def create_group_resp_msg(self,sender_id,resp_body):
        resp_msg = AgentMsg(AgentMsgType.TYPE_GROUPMSG)
        resp_msg.create_time = time.time()

        resp_msg.rely_msg_id = self.msg_id
        resp_msg.target = self.target
        resp_msg.sender = sender_id
        resp_msg.body = resp_body
        resp_msg.topic = self.topic

        return resp_msg

    def set(self,sender:str,target:str,body:str,topic:str=None) -> None:
        self.sender = sender
        self.target = target
        self.body = body
        self.create_time = time.time()
        if topic:
            self.topic = topic

    def get_msg_id(self) -> str:
        return self.msg_id

    def get_sender(self) -> str:
        return self.sender

    def get_target(self) -> str:
        return self.target
    
    def get_prev_msg_id(self) -> str:
        return self.prev_msg_id
    
    def get_quote_msg_id(self) -> str:
        return self.quote_msg_id
    
    @classmethod
    def parse_function_call(cls,func_string:str):
        str_list = shlex.split(func_string)
        func_name = str_list[0]
        params = str_list[1:]
        return func_name, params

class AgentPrompt:
    def __init__(self,prompt_str = None) -> None:
        self.messages = []
        if prompt_str:
            self.messages.append({"role":"user","content":prompt_str})
        self.system_message = None

    def as_str(self)->str:
        result_str = ""
        if self.system_message:
            result_str += self.system_message.get("role") + ":" + self.system_message.get("content") + "\n"
        if self.messages:
            for msg in self.messages:
                result_str += msg.get("role") + ":" + msg.get("content") + "\n"

        return result_str

    def to_message_list(self):
        result = []
        if self.system_message:
            result.append(self.system_message)
        result.extend(self.messages)
        return result

    def append(self,prompt):
        if prompt is None:
            return

        if prompt.system_message is not None:
            if self.system_message is None:
                self.system_message = copy.deepcopy(prompt.system_message)
            else:
                self.system_message["content"] += prompt.system_message.get("content")

        self.messages.extend(prompt.messages)

    def get_prompt_token_len(self):
        result = 0

        if self.system_message:
            result += len(self.system_message.get("content"))
        for msg in self.messages:
            result += len(msg.get("content"))

        return result

    def load_from_config(self,config:list) -> bool:
        if isinstance(config,list) is not True:
            logger.error("prompt is not list!")
            return False
        self.messages = []
        for msg in config:
            if msg.get("role") == "system":
                self.system_message = msg
            else:
                self.messages.append(msg)
        return True
        
class LLMResult:
    def __init__(self) -> None:
        self.state : str = "ignore"
        self.resp : str = ""
        self.paragraphs : dict[str,FunctionItem] = []
        self.post_msgs : List[AgentMsg] = []
        self.send_msgs : List[AgentMsg] = []
        self.calls : List[FunctionItem] = []
        self.post_calls : List[FunctionItem] = []

    @classmethod
    def from_str(self,llm_result_str:str,valid_func:List[str]=None) -> 'LLMResult':
        r = LLMResult()
        if llm_result_str is None:
            r.state = "ignore"
            return r
        if llm_result_str == "ignore":
            r.state = "ignore"
            return r

        lines = llm_result_str.splitlines()
        is_need_wait = False

        def check_args(func_item:FunctionItem):
            match func_name:
                case "send_msg":# /send_msg $target_id
                    if len(func_args) != 1:
                        return False
                    
                    new_msg = AgentMsg()
                    target_id = func_item.args[0]
                    msg_content = func_item.body
                    new_msg.set("",target_id,msg_content)

                    r.send_msgs.append(new_msg)
                    is_need_wait = True
                    return True

                case "post_msg":# /post_msg $target_id
                    if len(func_args) != 1:
                        return False
                    
                    new_msg = AgentMsg()
                    target_id = func_item.args[0]
                    msg_content = func_item.body
                    new_msg.set("",target_id,msg_content)
                    r.post_msgs.append(new_msg)
                    return True

                case "call":# /call $func_name $args_str
                    r.calls.append(func_item)
                    is_need_wait = True
                    return True
                case "post_call": # /post_call $func_name,$args_str
                    r.post_calls.append(func_item)
                    return True
                case _:
                    if valid_func is not None:
                        if func_name in valid_func:
                            r.paragraphs[func_name] = func_item
                            return True
            
            return False
                

        current_func : FunctionItem = None
        for line in lines:
            if line.startswith("##/"):
                if current_func:
                    if check_args(current_func) is False:
                        r.resp += current_func.dumps()

                func_name,func_args = AgentMsg.parse_function_call(line[3:])
                current_func = FunctionItem(func_name,func_args)
            else:
                if current_func:
                    current_func.append_body(line + "\n")
                else:
                    r.resp += line + "\n"

        if current_func:
            if check_args(current_func) is False:
                r.resp += current_func.dumps()

        if len(r.send_msgs) > 0 or len(r.calls) > 0:
            r.state = "waiting"
        else:
            r.state = "reponsed"

        return r    

class BaseAIAgent:
    def __init__(self) -> None:
        pass