package com.boyaa.antwars.view.screen.mail
{
   import starling.events.Event;
   
   public class MailBoxEvent extends Event
   {
      public static const MAIL_LIST_ITEM_SELECT_ICON_CLICK:String = "MAIL_LIST_ITEM_SELECT_ICON_CLICK";
      public static const MAIL_LIST_FILE_ONE_KEY:String = "MAIL_LIST_FILE_ONE_KEY";
      public static const MAIL_SELECT_EVENT:String = "MAIL_SELECT_EVENT";
      public static const MAIL_LIST_ALL_SELECT:String = "MAIL_LIST_ALL_SELECT";
      public static const MAIL_GOBACK_LIST_EVENT:String = "MAIL_GOBACK_LIST_EVENT";
      
      // Fix: Constructor signature to match (type, data) usage
      public function MailBoxEvent(type:String, data:Object = null, bubbles:Boolean = false)
      {
         // Starling Event constructor is (type, bubbles, data)
         // Usage in code was new MailBoxEvent(type, data)
         // So we map 2nd arg to data, and 3rd to bubbles (default false)
         super(type, bubbles, data);
      }
   }
}
