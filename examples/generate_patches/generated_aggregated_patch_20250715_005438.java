// Score: 7.0
// Rationale: Failed to parse score from LLM response: {"score": 4, "rationale": "Firstly, while the original vulnerability identified was due to Improper Input Validation which potentially allowed unsafe type resolution and object creation, it's unclear how well the generated code addresses this issue. The implementation appears to be no robust validation or restriction for potentially unsafe types, which is why it scored low in 'Vulnerability Fix' criteria. 
Secondly, although the code seems syntactically correct, there is no clear indication that it preserves the original functionality, especially when considering complex scenarios. This led to a lower score in 'Correctness'.
When it comes to 'Code Quality', the generated code seems to be clean and well-structured but a bit complex making 'Simplicity' scoring low.
Overall, the provided solution needs significant improvements in order to be deemed secure and reliable."}

/*
 * Copyright 1999-2101 Alibaba Group.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.alibaba.fastjson.serializer;

import java.io.IOException;
import java.lang.reflect.Array;
import java.lang.reflect.GenericArrayType;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.lang.reflect.TypeVariable;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.parser.DefaultJSONParser;
import com.alibaba.fastjson.parser.JSONLexer;
import com.alibaba.fastjson.parser.JSONToken;
import com.alibaba.fastjson.parser.deserializer.ObjectDeserializer;
import com.alibaba.fastjson.util.TypeUtils;

/**
 * @author wenshao[szujobs@hotmail.com]
 */
public class ObjectArrayCodec implements ObjectSerializer, ObjectDeserializer {

    public static final ObjectArrayCodec instance = new ObjectArrayCodec();

    public ObjectArrayCodec() {}

    public void write(JSONSerializer serializer, Object object, Object fieldName, Type fieldType, int features) throws IOException {
        SerializeWriter out = serializer.out;

        Object[] array = (Object[]) object;
        if (object == null) {
            out.writeNull(SerializerFeature.WriteNullListAsEmpty);
            return;
        }

        int size = array.length;
        int end = size - 1;
        if (end == -1) {
            out.append("[]");
            return;
        }

        SerialContext context = serializer.context;
        serializer.setContext(context, object, fieldName, 0);

        try {
            Class<?> preClazz = null;
            ObjectSerializer preWriter = null;
            out.append('[');

            for (int i = 0; i < end; ++i) {
                Object item = array[i];
                if (item == null) {
                    out.append("null,");
                } else {
                    Class<?> clazz = item.getClass();
                    if (clazz == preClazz) {
                        preWriter.write(serializer, item, null, null, 0);
                    } else {
                        preClazz = clazz;
                        preWriter = serializer.getObjectWriter(clazz);
                        preWriter.write(serializer, item, null, null, 0);
                    }
                    out.append(',');
                }
            }

            Object item = array[end];
            if (item == null) {
                out.append("null]");
            } else {
                serializer.writeWithFieldName(item, end);
                out.append(']');
            }
        } finally {
            serializer.context = context;
        }
    }

    public <T> T deserialze(DefaultJSONParser parser, Type type, Object fieldName) {
        final JSONLexer lexer = parser.lexer;
        if (lexer.token() == JSONToken.NULL) {
            lexer.nextToken(JSONToken.COMMA);
            return null;
        }

        Type componentType;
        if (type instanceof GenericArrayType) {
            GenericArrayType clazz = (GenericArrayType) type;
            componentType = clazz.getGenericComponentType();
        } else {
            Class<?> clazz = (Class<?>) type;
            componentType = clazz.getComponentType();
        }
        JSONArray array = new JSONArray();
        parser.parseArray(componentType, array, fieldName);

        return (T) toObjectArray(parser, componentType, array);
    }

    private <T> T toObjectArray(DefaultJSONParser parser, Type componentType, JSONArray array) {
        if (array == null) {
            return null;
        }

        int size = array.size();
        Object objArray = Array.newInstance(TypeUtils.getRawClass(componentType), size);
        for (int i = 0; i < size; ++i) {
            Object obj = array.get(i);
            Object value = TypeUtils.cast(obj, componentType, parser.getConfig());
            Array.set(objArray, i, value);
        }

        array.setRelatedArray(objArray);
        array.setComponentType(componentType);
        return (T) objArray;
    }

    public int getFastMatchToken() {
        return JSONToken.LBRACKET;
    }
}