package com.adobe.air.utils;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.res.Resources;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Environment;
import android.os.Process;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.util.HashMap;
import java.util.Scanner;

/* JADX INFO: loaded from: classes.dex */
public class Utils {
    private static String sRuntimePackageName;

    public static native boolean nativeConnectDebuggerSocket(String str);

    public static String getRuntimePackageName() {
        return sRuntimePackageName;
    }

    public static void setRuntimePackageName(String str) {
        sRuntimePackageName = str;
    }

    public static boolean hasCaptiveRuntime() {
        return !"com.adobe.air".equals(sRuntimePackageName);
    }

    static void KillProcess() {
        Process.killProcess(Process.myPid());
    }

    public static boolean writeStringToFile(String str, String str2) {
        File file = new File(str2);
        if (!file.exists()) {
            try {
                file.createNewFile();
            } catch (IOException e) {
                return false;
            }
        }
        byte[] bytes = str.getBytes();
        try {
            FileOutputStream fileOutputStream = new FileOutputStream(file);
            fileOutputStream.write(bytes, 0, bytes.length);
            fileOutputStream.close();
            return true;
        } catch (IOException e2) {
            return false;
        }
    }

    public static void writeOut(InputStream inputStream, File file) throws IOException {
        FileOutputStream fileOutputStream = new FileOutputStream(file);
        writeThrough(inputStream, fileOutputStream);
        fileOutputStream.close();
    }

    public static void writeThrough(InputStream inputStream, OutputStream outputStream) throws IOException {
        byte[] bArr = new byte[4096];
        while (true) {
            int i = inputStream.read(bArr);
            if (i != -1) {
                if (outputStream != null) {
                    outputStream.write(bArr, 0, i);
                    outputStream.flush();
                }
            } else {
                return;
            }
        }
    }

    public static void copyTo(File file, File file2) throws IOException {
        if (file.isDirectory()) {
            file2.mkdirs();
            for (File file3 : file.listFiles()) {
                copyTo(file3, new File(file2, file3.getName()));
            }
            return;
        }
        FileInputStream fileInputStream = new FileInputStream(file);
        FileOutputStream fileOutputStream = new FileOutputStream(file2);
        copyTo(fileInputStream, fileOutputStream);
        fileInputStream.close();
        fileOutputStream.close();
    }

    public static void copyTo(InputStream inputStream, OutputStream outputStream) throws IOException {
        byte[] bArr = new byte[1024];
        while (true) {
            int i = inputStream.read(bArr);
            if (i > 0) {
                outputStream.write(bArr, 0, i);
            } else {
                return;
            }
        }
    }

    public static void writeBufferToFile(StringBuffer stringBuffer, File file) throws IOException {
        FileWriter fileWriter = new FileWriter(file);
        fileWriter.write(stringBuffer.toString());
        fileWriter.close();
    }

    public static HashMap<String, String> parseKeyValuePairFile(File file, String str) throws IllegalStateException, FileNotFoundException {
        return parseKeyValuePairFile(new FileInputStream(file), str);
    }

    public static HashMap<String, String> parseKeyValuePairFile(InputStream inputStream, String str) throws IllegalStateException {
        HashMap<String, String> map = new HashMap<>();
        Scanner scanner = new Scanner(inputStream);
        while (scanner.hasNextLine()) {
            Scanner scanner2 = new Scanner(scanner.nextLine());
            scanner2.useDelimiter(str);
            if (scanner2.hasNext()) {
                map.put(scanner2.next().trim(), scanner2.next().trim());
            }
            scanner2.close();
        }
        scanner.close();
        return map;
    }

    public static void writeStringToFile(String str, File file) throws IOException {
        FileWriter fileWriter = new FileWriter(file);
        fileWriter.write(str);
        fileWriter.close();
    }

    public static String ReplaceTextContentWithStars(String str) {
        int length = str.length();
        char[] cArr = new char[length];
        for (int i = 0; i < length; i++) {
            cArr[i] = '*';
        }
        return new String(cArr);
    }

    public static String GetResourceStringFromRuntime(String str, Resources resources) {
        return resources.getString(resources.getIdentifier(str, "string", sRuntimePackageName));
    }

    public static View GetWidgetInViewByName(String str, Resources resources, View view) {
        return view.findViewById(resources.getIdentifier(str, "id", sRuntimePackageName));
    }

    public static View GetLayoutViewFromRuntime(String str, Resources resources, LayoutInflater layoutInflater) {
        int identifier = resources.getIdentifier(str, "layout", sRuntimePackageName);
        if (identifier != 0) {
            return layoutInflater.inflate(identifier, (ViewGroup) null);
        }
        return null;
    }

    public static String GetExternalStorageDirectory() {
        return Environment.getExternalStorageDirectory().getAbsolutePath();
    }

    public static String GetSharedDataDirectory() {
        return Environment.getDataDirectory().getAbsolutePath();
    }

    public static String GetLibCorePath(Context context) {
        return GetNativeLibraryPath(context, "libCore.so");
    }

    public static String GetLibSTLPath(Context context) {
        return GetNativeLibraryPath(context, "libstlport_shared.so");
    }

    public static String GetNativeLibraryPath(Context context, String str) {
        String strConcat = null;
        try {
            ApplicationInfo applicationInfo = context.getPackageManager().getApplicationInfo(sRuntimePackageName, 0);
            Field field = ApplicationInfo.class.getField("nativeLibraryDir");
            Field field2 = ApplicationInfo.class.getField("sourceDir");
            if (field != null) {
                if (((String) field2.get(applicationInfo)).startsWith("/system/app/")) {
                    strConcat = new String("/system/lib/" + sRuntimePackageName + "/" + str);
                } else {
                    strConcat = ((String) field.get(applicationInfo)).concat("/" + str);
                }
            }
        } catch (Exception e) {
        }
        if (strConcat == null) {
            return new String("/data/data/" + sRuntimePackageName + "/lib/" + str);
        }
        return strConcat;
    }

    public static String GetNativeExtensionPath(Context context, String str) {
        String str2;
        try {
            ApplicationInfo applicationInfo = context.getPackageManager().getApplicationInfo(sRuntimePackageName, 0);
            Field field = ApplicationInfo.class.getField("nativeLibraryDir");
            Field field2 = ApplicationInfo.class.getField("sourceDir");
            if (field == null) {
                str2 = null;
            } else if (((String) field2.get(applicationInfo)).startsWith("/system/app/")) {
                str2 = new String("/system/lib/" + sRuntimePackageName + "/" + str);
            } else {
                str2 = new String("/data/data/" + context.getPackageName() + "/lib/" + str);
            }
        } catch (Exception e) {
            str2 = null;
        }
        if (str2 == null) {
            return new String("/data/data/" + sRuntimePackageName + "/lib/" + str);
        }
        return str2;
    }

    public static String GetTelemetrySettings(Context context, String str, String str2) throws Throwable {
        InputStream inputStream;
        ByteArrayOutputStream byteArrayOutputStream;
        InputStream inputStreamOpen;
        ByteArrayOutputStream byteArrayOutputStream2;
        String str3;
        try {
            inputStreamOpen = context.getResources().getAssets().open(str, 1);
            try {
                byteArrayOutputStream2 = new ByteArrayOutputStream();
            } catch (Exception e) {
                byteArrayOutputStream2 = null;
            } catch (Throwable th) {
                byteArrayOutputStream = null;
                th = th;
                inputStream = inputStreamOpen;
            }
        } catch (Exception e2) {
            inputStreamOpen = null;
            byteArrayOutputStream2 = null;
        } catch (Throwable th2) {
            th = th2;
            inputStream = null;
            byteArrayOutputStream = null;
        }
        try {
            copyTo(inputStreamOpen, byteArrayOutputStream2);
            String string = byteArrayOutputStream2.toString();
            if (inputStreamOpen != null) {
                try {
                    inputStreamOpen.close();
                } catch (Exception e3) {
                    str3 = string;
                }
            }
            if (byteArrayOutputStream2 != null) {
                byteArrayOutputStream2.close();
            }
            str3 = string;
        } catch (Exception e4) {
            if (inputStreamOpen != null) {
                try {
                    inputStreamOpen.close();
                } catch (Exception e5) {
                    str3 = null;
                }
            }
            if (byteArrayOutputStream2 != null) {
                byteArrayOutputStream2.close();
            }
            str3 = null;
        } catch (Throwable th3) {
            byteArrayOutputStream = byteArrayOutputStream2;
            inputStream = inputStreamOpen;
            th = th3;
            if (inputStream != null) {
                try {
                    inputStream.close();
                } catch (Exception e6) {
                    throw th;
                }
            }
            if (byteArrayOutputStream != null) {
                byteArrayOutputStream.close();
            }
            throw th;
        }
        if (str3 == null) {
            try {
                return context.createPackageContext(str2, 0).getSharedPreferences("telemetry", 1).getString("content", "");
            } catch (Exception e7) {
                return str3;
            }
        }
        return str3;
    }

    public static boolean isNetworkAvailable(Context context) {
        NetworkInfo activeNetworkInfo = ((ConnectivityManager) context.getSystemService("connectivity")).getActiveNetworkInfo();
        if (activeNetworkInfo == null || !activeNetworkInfo.isConnected()) {
            return false;
        }
        return true;
    }
}
