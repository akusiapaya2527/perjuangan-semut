package
{
import flash.display.Sprite;
import flash.desktop.NativeApplication;
import flash.filesystem.File;
import flash.net.SharedObject;
import flash.utils.ByteArray;

   public class LoginSeed extends Sprite
   {
      public function LoginSeed():void
      {
         var so:SharedObject = SharedObject.getLocal("Antwars/LoginData");
         so.data["sid"] = "seed_auto_login";
         so.data["method"] = 1;
         so.data["assesToken"] = "";
          var ok:Boolean = so.flush();
          trace("SEED flush(sid=seed_auto_login,method=1) => " + ok);
          // single-instance app id: MUST exit or the real client launch gets
          // forwarded to this instance instead of starting fresh.
          NativeApplication.nativeApplication.exit(0);
          var base:File = File.applicationStorageDirectory;
         trace("SEED storage root: " + base.nativePath);
         walk(base, 0);
      }

      private function walk(dir:File, depth:int):void
      {
         var entries:Array = dir.getDirectoryListing();
         entries.sortOn("name");
         for each (var e:File in entries)
         {
            var tag:String = e.isDirectory ? "DIR " : "FILE";
            trace("SEED " + pad(depth) + tag + " " + e.name);
            if (e.isDirectory)
            {
               walk(e, depth + 1);
            }
         }
      }

      private function pad(n:int):String
      {
         var s:String = "";
         for (var i:int = 0; i < n; i++)
         {
            s += "  ";
         }
         return s;
      }
   }
}