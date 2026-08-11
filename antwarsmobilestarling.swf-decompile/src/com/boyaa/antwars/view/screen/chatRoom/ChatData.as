package com.boyaa.antwars.view.screen.chatRoom
{
   public class ChatData
   {
      
      private var _msg:String;
      
      private var _mid:int;

      private var _timestamp:String;
      
      public function ChatData()
      {
         super();
      }
      
      public function readData(param1:String, param2:int = 1) : void
      {
         _msg = param1;
         _mid = param2;
         _timestamp = formatTimestamp(new Date());
      }

      private function formatTimestamp(param1:Date) : String
      {
         var _loc2_:String = param1.fullYear.toString();
         var _loc3_:String = (param1.month + 1).toString();
         var _loc4_:String = param1.date.toString();
         var _loc5_:String = param1.hours.toString();
         var _loc6_:String = param1.minutes.toString();
         if(_loc3_.length < 2)
         {
            _loc3_ = "0" + _loc3_;
         }
         if(_loc4_.length < 2)
         {
            _loc4_ = "0" + _loc4_;
         }
         if(_loc5_.length < 2)
         {
            _loc5_ = "0" + _loc5_;
         }
         if(_loc6_.length < 2)
         {
            _loc6_ = "0" + _loc6_;
         }
         return _loc2_ + "-" + _loc3_ + "-" + _loc4_ + " " + _loc5_ + ":" + _loc6_;
      }
      
      public function get msg() : String
      {
         return _msg;
      }
      
      public function set msg(param1:String) : void
      {
         _msg = param1;
      }
      
      public function get mid() : int
      {
         return _mid;
      }
      
      public function set mid(param1:int) : void
      {
         _mid = param1;
      }

      public function get timestamp() : String
      {
         return _timestamp;
      }

      public function set timestamp(param1:String) : void
      {
         _timestamp = param1;
      }
   }
}
