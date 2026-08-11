package com.facebook.internal;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import com.facebook.FacebookException;
import com.facebook.internal.ImageRequest;
import com.facebook.internal.WorkQueue;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.util.HashMap;
import java.util.Map;

/* JADX INFO: loaded from: classes.dex */
public class ImageDownloader {
    private static final int CACHE_READ_QUEUE_MAX_CONCURRENT = 2;
    private static final int DOWNLOAD_QUEUE_MAX_CONCURRENT = 8;
    private static Handler handler;
    private static WorkQueue downloadQueue = new WorkQueue(8);
    private static WorkQueue cacheReadQueue = new WorkQueue(2);
    private static final Map<RequestKey, DownloaderContext> pendingRequests = new HashMap();

    private static class CacheReadWorkItem implements Runnable {
        private boolean allowCachedRedirects;
        private Context context;
        private RequestKey key;

        CacheReadWorkItem(Context context, RequestKey requestKey, boolean z) {
            this.context = context;
            this.key = requestKey;
            this.allowCachedRedirects = z;
        }

        @Override // java.lang.Runnable
        public void run() {
            ImageDownloader.readFromCache(this.key, this.context, this.allowCachedRedirects);
        }
    }

    private static class DownloadImageWorkItem implements Runnable {
        private Context context;
        private RequestKey key;

        DownloadImageWorkItem(Context context, RequestKey requestKey) {
            this.context = context;
            this.key = requestKey;
        }

        @Override // java.lang.Runnable
        public void run() throws Throwable {
            ImageDownloader.download(this.key, this.context);
        }
    }

    private static class DownloaderContext {
        boolean isCancelled;
        ImageRequest request;
        WorkQueue.WorkItem workItem;

        private DownloaderContext() {
        }
    }

    private static class RequestKey {
        private static final int HASH_MULTIPLIER = 37;
        private static final int HASH_SEED = 29;
        Object tag;
        URI uri;

        RequestKey(URI uri, Object obj) {
            this.uri = uri;
            this.tag = obj;
        }

        public boolean equals(Object obj) {
            if (obj == null || !(obj instanceof RequestKey)) {
                return false;
            }
            RequestKey requestKey = (RequestKey) obj;
            return requestKey.uri == this.uri && requestKey.tag == this.tag;
        }

        public int hashCode() {
            int i = HASH_SEED * HASH_MULTIPLIER;
            return ((this.uri.hashCode() + 1073) * HASH_MULTIPLIER) + this.tag.hashCode();
        }
    }

    public static boolean cancelRequest(ImageRequest imageRequest) {
        boolean z = false;
        RequestKey requestKey = new RequestKey(imageRequest.getImageUri(), imageRequest.getCallerTag());
        synchronized (pendingRequests) {
            DownloaderContext downloaderContext = pendingRequests.get(requestKey);
            if (downloaderContext != null) {
                if (downloaderContext.workItem.cancel()) {
                    pendingRequests.remove(requestKey);
                    z = true;
                } else {
                    downloaderContext.isCancelled = true;
                    z = true;
                }
            }
        }
        return z;
    }

    public static void clearCache(Context context) {
        ImageResponseCache.clearCache(context);
        UrlRedirectCache.clearCache(context);
    }

    /* JADX INFO: Access modifiers changed from: private */
    /* JADX WARN: Failed to find 'out' block for switch in B:6:0x001c. Please report as an issue. */
    /* JADX WARN: Multi-variable type inference failed */
    /* JADX WARN: Type inference failed for: r1v1 */
    /* JADX WARN: Type inference failed for: r1v11 */
    /* JADX WARN: Type inference failed for: r1v2, types: [java.io.Closeable] */
    /* JADX WARN: Type inference failed for: r1v9 */
    /* JADX WARN: Type inference failed for: r2v1 */
    /* JADX WARN: Type inference failed for: r2v13 */
    /* JADX WARN: Type inference failed for: r2v15 */
    /* JADX WARN: Type inference failed for: r2v17, types: [int] */
    /* JADX WARN: Type inference failed for: r2v19 */
    /* JADX WARN: Type inference failed for: r2v2 */
    /* JADX WARN: Type inference failed for: r2v20 */
    /* JADX WARN: Type inference failed for: r2v32 */
    /* JADX WARN: Type inference failed for: r2v33 */
    /* JADX WARN: Type inference failed for: r2v4, types: [java.io.Closeable] */
    /* JADX WARN: Type inference failed for: r2v6, types: [java.io.Closeable] */
    public static void download(RequestKey requestKey, Context context) throws Throwable {
        ?? r1;
        HttpURLConnection httpURLConnection;
        ?? r2;
        HttpURLConnection httpURLConnection2;
        ?? r22;
        HttpURLConnection httpURLConnection3;
        Exception exc;
        boolean z;
        Bitmap bitmap;
        HttpURLConnection httpURLConnection4;
        ?? responseCode;
        Bitmap bitmapDecodeStream;
        FacebookException facebookException;
        InputStream inputStream;
        boolean z2 = true;
        try {
            httpURLConnection4 = (HttpURLConnection) new URL(requestKey.uri.toString()).openConnection();
        } catch (IOException e) {
            e = e;
            r22 = 0;
            httpURLConnection3 = null;
        } catch (URISyntaxException e2) {
            e = e2;
            r2 = 0;
            httpURLConnection2 = null;
        } catch (Throwable th) {
            th = th;
            r1 = 0;
            httpURLConnection = null;
        }
        try {
            try {
                httpURLConnection4.setInstanceFollowRedirects(false);
                responseCode = httpURLConnection4.getResponseCode();
            } catch (Throwable th2) {
                httpURLConnection = httpURLConnection4;
                th = th2;
                r1 = 0;
            }
            try {
                switch (responseCode) {
                    case 200:
                        InputStream inputStreamInterceptAndCacheImageStream = ImageResponseCache.interceptAndCacheImageStream(context, httpURLConnection4);
                        inputStream = inputStreamInterceptAndCacheImageStream;
                        bitmapDecodeStream = BitmapFactory.decodeStream(inputStreamInterceptAndCacheImageStream);
                        facebookException = null;
                        Utility.closeQuietly(inputStream);
                        Utility.disconnectQuietly(httpURLConnection4);
                        z = z2;
                        bitmap = bitmapDecodeStream;
                        exc = facebookException;
                        break;
                    case 301:
                    case 302:
                        try {
                            String headerField = httpURLConnection4.getHeaderField("location");
                            if (Utility.isNullOrEmpty(headerField)) {
                                z2 = false;
                                bitmapDecodeStream = null;
                                facebookException = null;
                                inputStream = null;
                            } else {
                                URI uri = new URI(headerField);
                                UrlRedirectCache.cacheUriRedirect(context, requestKey.uri, uri);
                                DownloaderContext downloaderContextRemovePendingRequest = removePendingRequest(requestKey);
                                if (downloaderContextRemovePendingRequest != null && !downloaderContextRemovePendingRequest.isCancelled) {
                                    enqueueCacheRead(downloaderContextRemovePendingRequest.request, new RequestKey(uri, requestKey.tag), false);
                                }
                                z2 = false;
                                bitmapDecodeStream = null;
                                facebookException = null;
                                inputStream = null;
                            }
                            Utility.closeQuietly(inputStream);
                            Utility.disconnectQuietly(httpURLConnection4);
                            z = z2;
                            bitmap = bitmapDecodeStream;
                            exc = facebookException;
                        } catch (IOException e3) {
                            r22 = 0;
                            httpURLConnection3 = httpURLConnection4;
                            e = e3;
                            z2 = false;
                            Utility.closeQuietly(r22);
                            Utility.disconnectQuietly(httpURLConnection3);
                            exc = e;
                            z = z2;
                            bitmap = null;
                        } catch (URISyntaxException e4) {
                            r2 = 0;
                            httpURLConnection2 = httpURLConnection4;
                            e = e4;
                            z2 = false;
                            Utility.closeQuietly(r2);
                            Utility.disconnectQuietly(httpURLConnection2);
                            exc = e;
                            z = z2;
                            bitmap = null;
                        }
                        break;
                    default:
                        InputStream errorStream = httpURLConnection4.getErrorStream();
                        InputStreamReader inputStreamReader = new InputStreamReader(errorStream);
                        char[] cArr = new char[128];
                        StringBuilder sb = new StringBuilder();
                        while (true) {
                            int i = inputStreamReader.read(cArr, 0, cArr.length);
                            if (i <= 0) {
                                Utility.closeQuietly(inputStreamReader);
                                facebookException = new FacebookException(sb.toString());
                                inputStream = errorStream;
                                bitmapDecodeStream = null;
                                Utility.closeQuietly(inputStream);
                                Utility.disconnectQuietly(httpURLConnection4);
                                z = z2;
                                bitmap = bitmapDecodeStream;
                                exc = facebookException;
                            } else {
                                sb.append(cArr, 0, i);
                            }
                            break;
                        }
                        break;
                }
            } catch (IOException e5) {
                httpURLConnection3 = httpURLConnection4;
                e = e5;
                r22 = responseCode;
            } catch (URISyntaxException e6) {
                httpURLConnection2 = httpURLConnection4;
                e = e6;
                r2 = responseCode;
            } catch (Throwable th3) {
                r1 = responseCode;
                httpURLConnection = httpURLConnection4;
                th = th3;
                Utility.closeQuietly(r1);
                Utility.disconnectQuietly(httpURLConnection);
                throw th;
            }
        } catch (IOException e7) {
            httpURLConnection3 = httpURLConnection4;
            e = e7;
            r22 = 0;
        } catch (URISyntaxException e8) {
            httpURLConnection2 = httpURLConnection4;
            e = e8;
            r2 = 0;
        }
        if (z) {
            issueResponse(requestKey, exc, bitmap, false);
        }
    }

    public static void downloadAsync(ImageRequest imageRequest) {
        if (imageRequest == null) {
            return;
        }
        RequestKey requestKey = new RequestKey(imageRequest.getImageUri(), imageRequest.getCallerTag());
        synchronized (pendingRequests) {
            DownloaderContext downloaderContext = pendingRequests.get(requestKey);
            if (downloaderContext != null) {
                downloaderContext.request = imageRequest;
                downloaderContext.isCancelled = false;
                downloaderContext.workItem.moveToFront();
            } else {
                enqueueCacheRead(imageRequest, requestKey, imageRequest.isCachedRedirectAllowed());
            }
        }
    }

    private static void enqueueCacheRead(ImageRequest imageRequest, RequestKey requestKey, boolean z) {
        enqueueRequest(imageRequest, requestKey, cacheReadQueue, new CacheReadWorkItem(imageRequest.getContext(), requestKey, z));
    }

    private static void enqueueDownload(ImageRequest imageRequest, RequestKey requestKey) {
        enqueueRequest(imageRequest, requestKey, downloadQueue, new DownloadImageWorkItem(imageRequest.getContext(), requestKey));
    }

    private static void enqueueRequest(ImageRequest imageRequest, RequestKey requestKey, WorkQueue workQueue, Runnable runnable) {
        synchronized (pendingRequests) {
            DownloaderContext downloaderContext = new DownloaderContext();
            downloaderContext.request = imageRequest;
            pendingRequests.put(requestKey, downloaderContext);
            downloaderContext.workItem = workQueue.addActiveWorkItem(runnable);
        }
    }

    private static synchronized Handler getHandler() {
        if (handler == null) {
            handler = new Handler(Looper.getMainLooper());
        }
        return handler;
    }

    private static void issueResponse(RequestKey requestKey, final Exception exc, final Bitmap bitmap, final boolean z) {
        final ImageRequest imageRequest;
        final ImageRequest.Callback callback;
        DownloaderContext downloaderContextRemovePendingRequest = removePendingRequest(requestKey);
        if (downloaderContextRemovePendingRequest == null || downloaderContextRemovePendingRequest.isCancelled || (callback = (imageRequest = downloaderContextRemovePendingRequest.request).getCallback()) == null) {
            return;
        }
        getHandler().post(new Runnable() { // from class: com.facebook.internal.ImageDownloader.1
            @Override // java.lang.Runnable
            public void run() {
                callback.onCompleted(new ImageResponse(imageRequest, exc, z, bitmap));
            }
        });
    }

    public static void prioritizeRequest(ImageRequest imageRequest) {
        RequestKey requestKey = new RequestKey(imageRequest.getImageUri(), imageRequest.getCallerTag());
        synchronized (pendingRequests) {
            DownloaderContext downloaderContext = pendingRequests.get(requestKey);
            if (downloaderContext != null) {
                downloaderContext.workItem.moveToFront();
            }
        }
    }

    /* JADX INFO: Access modifiers changed from: private */
    public static void readFromCache(RequestKey requestKey, Context context, boolean z) {
        boolean z2;
        InputStream cachedImageStream;
        URI redirectedUri;
        if (!z || (redirectedUri = UrlRedirectCache.getRedirectedUri(context, requestKey.uri)) == null) {
            z2 = false;
            cachedImageStream = null;
        } else {
            InputStream cachedImageStream2 = ImageResponseCache.getCachedImageStream(redirectedUri, context);
            cachedImageStream = cachedImageStream2;
            z2 = cachedImageStream2 != null;
        }
        if (!z2) {
            cachedImageStream = ImageResponseCache.getCachedImageStream(requestKey.uri, context);
        }
        if (cachedImageStream != null) {
            Bitmap bitmapDecodeStream = BitmapFactory.decodeStream(cachedImageStream);
            Utility.closeQuietly(cachedImageStream);
            issueResponse(requestKey, null, bitmapDecodeStream, z2);
        } else {
            DownloaderContext downloaderContextRemovePendingRequest = removePendingRequest(requestKey);
            if (downloaderContextRemovePendingRequest == null || downloaderContextRemovePendingRequest.isCancelled) {
                return;
            }
            enqueueDownload(downloaderContextRemovePendingRequest.request, requestKey);
        }
    }

    private static DownloaderContext removePendingRequest(RequestKey requestKey) {
        DownloaderContext downloaderContextRemove;
        synchronized (pendingRequests) {
            downloaderContextRemove = pendingRequests.remove(requestKey);
        }
        return downloaderContextRemove;
    }
}
