package com.adobe.air;

import android.app.Activity;
import android.app.Application;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Matrix;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.provider.MediaStore;
import com.adobe.air.AndroidActivityWrapper;
import java.io.OutputStream;

/* JADX INFO: loaded from: classes.dex */
public class AndroidMediaManager {
    public static final int ERROR_ACTIVITY_DESTROYED = 2;
    public static final int ERROR_IMAGE_PICKER_NOT_FOUND = 1;
    private static long MediaManagerObjectPointer = 0;
    private static final String PHONE_STORAGE = "phoneStorage";
    private boolean mCallbacksRegistered = false;
    private AndroidActivityWrapper.ActivityResultCallback mActivityResultCB = null;

    public native void useImagePickerData(long j, boolean z, boolean z2, String str, String str2, String str3);

    public AndroidMediaManager() {
        MediaManagerObjectPointer = 0L;
    }

    public void registerCallbacks() {
        doCallbackRegistration(true);
    }

    public void unregisterCallbacks() {
        doCallbackRegistration(false);
    }

    private void doCallbackRegistration(boolean z) {
        this.mCallbacksRegistered = z;
        if (z) {
            if (this.mActivityResultCB == null) {
                this.mActivityResultCB = new AndroidActivityWrapper.ActivityResultCallback() { // from class: com.adobe.air.AndroidMediaManager.1
                    @Override // com.adobe.air.AndroidActivityWrapper.ActivityResultCallback
                    public void onActivityResult(int i, int i2, Intent intent) {
                        if (i == 2 && AndroidMediaManager.MediaManagerObjectPointer != 0 && AndroidMediaManager.this.mCallbacksRegistered) {
                            AndroidMediaManager.this.onBrowseImageResult(i2, intent, AndroidActivityWrapper.GetAndroidActivityWrapper().getActivity());
                            AndroidMediaManager.this.unregisterCallbacks();
                        }
                    }
                };
            }
            AndroidActivityWrapper.GetAndroidActivityWrapper().addActivityResultListener(this.mActivityResultCB);
        } else if (this.mActivityResultCB != null) {
            AndroidActivityWrapper.GetAndroidActivityWrapper().removeActivityResultListener(this.mActivityResultCB);
            this.mActivityResultCB = null;
        }
    }

    public static boolean AddImage(Application application, Bitmap bitmap, boolean z) {
        String strSaveImage;
        if (application != null) {
            ContentResolver contentResolver = application.getContentResolver();
            try {
                strSaveImage = MediaStore.Images.Media.insertImage(contentResolver, bitmap, (String) null, (String) null);
            } catch (Exception e) {
                strSaveImage = null;
            }
            if (strSaveImage == null) {
                strSaveImage = SaveImage(PHONE_STORAGE, contentResolver, bitmap, z);
            }
            if (strSaveImage != null) {
                try {
                    Cursor cursorQuery = contentResolver.query(Uri.parse(strSaveImage), new String[]{"_data"}, null, null, null);
                    if (cursorQuery != null) {
                        int columnIndexOrThrow = cursorQuery.getColumnIndexOrThrow("_data");
                        cursorQuery.moveToFirst();
                        MediaScannerConnection.scanFile(AndroidActivityWrapper.GetAndroidActivityWrapper().getDefaultContext(), new String[]{cursorQuery.getString(columnIndexOrThrow)}, null, null);
                    }
                } catch (Exception e2) {
                }
                return true;
            }
        }
        return false;
    }

    /* JADX WARN: Removed duplicated region for block: B:13:0x0068  */
    /* JADX WARN: Removed duplicated region for block: B:20:0x0079  */
    /* JADX WARN: Removed duplicated region for block: B:35:0x0095  */
    /*
        Code decompiled incorrectly, please refer to instructions dump.
        To view partially-correct add '--show-bad-code' argument
    */
    private static java.lang.String SaveImage(java.lang.String r11, android.content.ContentResolver r12, android.graphics.Bitmap r13, boolean r14) {
        /*
            r10 = 0
            java.lang.String r0 = "mime_type"
            android.content.ContentValues r0 = new android.content.ContentValues     // Catch: java.lang.Exception -> L75
            r0.<init>()     // Catch: java.lang.Exception -> L75
            if (r14 == 0) goto L6d
            java.lang.String r1 = "mime_type"
            java.lang.String r2 = "image/jpeg"
            r0.put(r1, r2)     // Catch: java.lang.Exception -> L75
        L11:
            java.util.Date r1 = new java.util.Date     // Catch: java.lang.Exception -> L75
            r1.<init>()     // Catch: java.lang.Exception -> L75
            java.lang.String r2 = "datetaken"
            long r3 = r1.getTime()     // Catch: java.lang.Exception -> L75
            java.lang.Long r3 = java.lang.Long.valueOf(r3)     // Catch: java.lang.Exception -> L75
            r0.put(r2, r3)     // Catch: java.lang.Exception -> L75
            java.lang.String r2 = "date_added"
            long r3 = r1.getTime()     // Catch: java.lang.Exception -> L75
            r5 = 1000(0x3e8, double:4.94E-321)
            long r3 = r3 / r5
            java.lang.Long r1 = java.lang.Long.valueOf(r3)     // Catch: java.lang.Exception -> L75
            r0.put(r2, r1)     // Catch: java.lang.Exception -> L75
            android.net.Uri r1 = android.provider.MediaStore.Images.Media.getContentUri(r11)     // Catch: java.lang.Exception -> L75
            android.net.Uri r8 = r12.insert(r1, r0)     // Catch: java.lang.Exception -> L75
            if (r8 == 0) goto L99
            java.io.OutputStream r9 = r12.openOutputStream(r8)     // Catch: java.lang.Exception -> L92
            android.graphics.Bitmap$CompressFormat r0 = android.graphics.Bitmap.CompressFormat.JPEG     // Catch: java.lang.Exception -> L7e java.lang.Throwable -> L8d
            r1 = 90
            r13.compress(r0, r1, r9)     // Catch: java.lang.Exception -> L7e java.lang.Throwable -> L8d
            long r3 = android.content.ContentUris.parseId(r8)     // Catch: java.lang.Exception -> L7e java.lang.Throwable -> L8d
            r5 = 1134559232(0x43a00000, float:320.0)
            r6 = 1131413504(0x43700000, float:240.0)
            r7 = 1
            r0 = r11
            r1 = r12
            r2 = r13
            android.graphics.Bitmap r2 = SaveThumbnail(r0, r1, r2, r3, r5, r6, r7)     // Catch: java.lang.Exception -> L7e java.lang.Throwable -> L8d
            r5 = 1112014848(0x42480000, float:50.0)
            r6 = 1112014848(0x42480000, float:50.0)
            r7 = 3
            r0 = r11
            r1 = r12
            SaveThumbnail(r0, r1, r2, r3, r5, r6, r7)     // Catch: java.lang.Exception -> L7e java.lang.Throwable -> L8d
            r9.close()     // Catch: java.lang.Exception -> L92
            r0 = r8
        L66:
            if (r0 == 0) goto L95
            java.lang.String r0 = r0.toString()
        L6c:
            return r0
        L6d:
            java.lang.String r1 = "mime_type"
            java.lang.String r2 = "image/png"
            r0.put(r1, r2)     // Catch: java.lang.Exception -> L75
            goto L11
        L75:
            r0 = move-exception
            r0 = r10
        L77:
            if (r0 == 0) goto L66
            r12.delete(r0, r10, r10)
            r0 = r10
            goto L66
        L7e:
            r0 = move-exception
            if (r8 == 0) goto L97
            r0 = 0
            r1 = 0
            r12.delete(r8, r0, r1)     // Catch: java.lang.Throwable -> L8d
            r0 = r10
        L87:
            r9.close()     // Catch: java.lang.Exception -> L8b
            goto L66
        L8b:
            r1 = move-exception
            goto L77
        L8d:
            r0 = move-exception
            r9.close()     // Catch: java.lang.Exception -> L92
            throw r0     // Catch: java.lang.Exception -> L92
        L92:
            r0 = move-exception
            r0 = r8
            goto L77
        L95:
            r0 = r10
            goto L6c
        L97:
            r0 = r8
            goto L87
        L99:
            r0 = r8
            goto L66
        */
        throw new UnsupportedOperationException("Method not decompiled: com.adobe.air.AndroidMediaManager.SaveImage(java.lang.String, android.content.ContentResolver, android.graphics.Bitmap, boolean):java.lang.String");
    }

    private static final Bitmap SaveThumbnail(String str, ContentResolver contentResolver, Bitmap bitmap, long j, float f, float f2, int i) {
        Uri uriInsert;
        if (bitmap == null) {
            return null;
        }
        Matrix matrix = new Matrix();
        try {
            matrix.setScale(f / bitmap.getWidth(), f2 / bitmap.getHeight());
            Bitmap bitmapCreateBitmap = Bitmap.createBitmap(bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true);
            ContentValues contentValues = new ContentValues(4);
            contentValues.put("kind", Integer.valueOf(i));
            contentValues.put("image_id", Integer.valueOf((int) j));
            contentValues.put("height", Integer.valueOf(bitmapCreateBitmap.getHeight()));
            contentValues.put("width", Integer.valueOf(bitmapCreateBitmap.getWidth()));
            try {
                uriInsert = contentResolver.insert(MediaStore.Images.Thumbnails.getContentUri(str), contentValues);
                if (uriInsert != null) {
                    try {
                        OutputStream outputStreamOpenOutputStream = contentResolver.openOutputStream(uriInsert);
                        bitmapCreateBitmap.compress(Bitmap.CompressFormat.JPEG, 100, outputStreamOpenOutputStream);
                        outputStreamOpenOutputStream.close();
                    } catch (Exception e) {
                        if (uriInsert != null) {
                            contentResolver.delete(uriInsert, null, null);
                            uriInsert = null;
                        }
                    }
                }
            } catch (Exception e2) {
                uriInsert = null;
            }
            if (uriInsert == null) {
                return null;
            }
            return bitmapCreateBitmap;
        } catch (Exception e3) {
            return null;
        }
    }

    public int BrowseImage(long j) {
        int i = 0;
        try {
            AndroidActivityWrapper androidActivityWrapperGetAndroidActivityWrapper = AndroidActivityWrapper.GetAndroidActivityWrapper();
            Intent intent = new Intent();
            intent.setType("image/*");
            intent.setAction("android.intent.action.PICK");
            if (androidActivityWrapperGetAndroidActivityWrapper.getActivity() != null) {
                androidActivityWrapperGetAndroidActivityWrapper.getActivity().startActivityForResult(Intent.createChooser(intent, ""), 2);
            } else {
                i = 2;
            }
        } catch (ActivityNotFoundException e) {
            i = 1;
        }
        if (i == 0) {
            registerCallbacks();
            MediaManagerObjectPointer = j;
        }
        return i;
    }

    public void onBrowseImageResult(int i, Intent intent, Activity activity) {
        if (i == 0) {
            useImagePickerData(MediaManagerObjectPointer, false, true, "", "", "");
            return;
        }
        if (i == -1) {
            try {
                Cursor cursorManagedQuery = activity.managedQuery(intent.getData(), new String[]{"_data", "mime_type", "_display_name"}, null, null, null);
                if (cursorManagedQuery == null) {
                    useImagePickerData(MediaManagerObjectPointer, false, false, "", "", "");
                } else {
                    int columnIndexOrThrow = cursorManagedQuery.getColumnIndexOrThrow("_data");
                    int columnIndexOrThrow2 = cursorManagedQuery.getColumnIndexOrThrow("_display_name");
                    cursorManagedQuery.moveToFirst();
                    useImagePickerData(MediaManagerObjectPointer, true, true, cursorManagedQuery.getString(columnIndexOrThrow), "image", cursorManagedQuery.getString(columnIndexOrThrow2));
                }
            } catch (IllegalArgumentException e) {
                useImagePickerData(MediaManagerObjectPointer, false, false, "", "", "");
            } catch (Exception e2) {
                useImagePickerData(MediaManagerObjectPointer, false, false, "", "", "");
            }
        }
    }
}
